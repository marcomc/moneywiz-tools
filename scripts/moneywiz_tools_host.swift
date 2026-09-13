import AppKit
import CoreData
import CryptoKit
import Darwin
import Foundation

private let expectedBundleIdentifier = "com.marcomc.moneywiz-tools"
private let moneyWizBundleIdentifiers = [
    "com.moneywiz.personalfinance-setapp",
    "com.moneywiz.personalfinance",
]
private let transactionAuthor = "MWLocalAuthor"
private let modelChecksumMetadataKey = "NSStoreModelVersionChecksumKey"

#if MONEYWIZ_TOOLS_TESTING
enum WriterTestCrashPoint { case beforeSave, afterSave }
var writerTestCrashPoint: WriterTestCrashPoint?
#endif

struct WriterPolicy {
    let profileID: String
    let modelChecksum: String
    let capability: String
    let schemaVersion: Int
    let transactionEntities: Set<String>
}

private let supportedWriterPolicy = WriterPolicy(
    profileID: "moneywiz-2026-model-48",
    modelChecksum: "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
    capability: "write.reassign-payees-by-id",
    schemaVersion: 1,
    transactionEntities: Set([
        "DepositTransaction",
        "InvestmentExchangeTransaction",
        "InvestmentBuyTransaction",
        "InvestmentSellTransaction",
        "ReconcileTransaction",
        "RefundTransaction",
        "TransferBudgetTransaction",
        "TransferDepositTransaction",
        "TransferWithdrawTransaction",
        "WithdrawTransaction",
    ])
)

final class PassthroughTransformer: ValueTransformer {
    override class func allowsReverseTransformation() -> Bool { true }
    override class func transformedValueClass() -> AnyClass { NSObject.self }
    override func transformedValue(_ value: Any?) -> Any? { value }
    override func reverseTransformedValue(_ value: Any?) -> Any? { value }
}

struct WriterArguments {
    let store: URL
    let model: URL
    let plan: URL
    let recoverOnly: Bool
}

struct WriterPlan: Decodable {
    let contractVersion: Int
    let profileID: String
    let modelChecksum: String
    let capability: String
    let schemaVersion: Int
    let operations: [WriterOperation]
    let payeeMerges: [PayeeMerge]?

    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version"
        case profileID = "profile_id"
        case modelChecksum = "model_checksum"
        case capability
        case schemaVersion = "schema_version"
        case operations
        case payeeMerges = "payee_merges"
    }
}

struct WriterOperation: Decodable {
    let transactionGID: String
    let transactionEntity: String
    let existingPayeeGID: String?
    let newPayeeKey: String?
    let newPayeeName: String?

    enum CodingKeys: String, CodingKey {
        case transactionGID = "transaction_gid"
        case transactionEntity = "transaction_entity"
        case existingPayeeGID = "existing_payee_gid"
        case newPayeeKey = "new_payee_key"
        case newPayeeName = "new_payee_name"
    }
}

struct PayeeMerge: Decodable {
    let sourcePayeeGID: String
    let targetPayeeGID: String

    enum CodingKeys: String, CodingKey {
        case sourcePayeeGID = "source_payee_gid"
        case targetPayeeGID = "target_payee_gid"
    }
}

struct WriterResult: Encodable {
    let createdPayees: Int
    let reassignedTransactions: Int
    let mergedPayees: Int
    let migratedRelationships: Int

    enum CodingKeys: String, CodingKey {
        case createdPayees = "created_payees"
        case reassignedTransactions = "reassigned_transactions"
        case mergedPayees = "merged_payees"
        case migratedRelationships = "migrated_relationships"
    }
}

enum HostError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case .message(let message):
            return message
        }
    }
}

func parseWriterArguments() throws -> WriterArguments {
    let invocation = Array(CommandLine.arguments.dropFirst())
    guard invocation.first == "--coredata-write" || invocation.first == "--coredata-recover" else {
        throw HostError.message(
            "usage: MoneyWizTools --coredata-write --store PATH --model PATH --plan PATH"
        )
    }
    let arguments = Array(invocation.dropFirst())
    guard arguments.count == 6 else {
        throw HostError.message(
            "usage: MoneyWizTools --coredata-write --store PATH --model PATH --plan PATH"
        )
    }

    var values: [String: String] = [:]
    var index = 0
    while index < arguments.count {
        let flag = arguments[index]
        let value = arguments[index + 1]
        guard ["--store", "--model", "--plan"].contains(flag), values[flag] == nil else {
            throw HostError.message(
                "invalid arguments; expected --store PATH --model PATH --plan PATH"
            )
        }
        values[flag] = value
        index += 2
    }

    guard let storePath = values["--store"],
          let modelPath = values["--model"],
          let planPath = values["--plan"] else {
        throw HostError.message("missing required --store, --model, or --plan argument")
    }
    return WriterArguments(
        store: URL(fileURLWithPath: storePath),
        model: URL(fileURLWithPath: modelPath),
        plan: URL(fileURLWithPath: planPath),
        recoverOnly: invocation.first == "--coredata-recover"
    )
}

func configureTransformers() {
    for name in ["HMRCMappingTransformer", "TransactionsFilterArrayTransformer", "UIColorTransformer"] {
        ValueTransformer.setValueTransformer(
            PassthroughTransformer(), forName: NSValueTransformerName(name)
        )
    }
}

func fetchExactObject(
    entityName: String,
    gid: String,
    context: NSManagedObjectContext
) throws -> NSManagedObject {
    let request = NSFetchRequest<NSManagedObject>(entityName: entityName)
    request.fetchLimit = 2
    request.includesSubentities = false
    request.predicate = NSPredicate(format: "GID == %@", gid)
    let results = try context.fetch(request)
    guard results.count == 1,
          let object = results.first,
          object.entity.name == entityName else {
        throw HostError.message("expected one \(entityName) with GID \(gid), found \(results.count)")
    }
    return object
}

func isBlank(_ value: String) -> Bool {
    value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
}

func validateOperation(_ operation: WriterOperation, policy: WriterPolicy) throws {
    guard !isBlank(operation.transactionGID),
          policy.transactionEntities.contains(operation.transactionEntity) else {
        throw HostError.message(
            "writer operation must identify an allowed transaction entity and nonblank GID"
        )
    }

    if let existingPayeeGID = operation.existingPayeeGID {
        guard !isBlank(existingPayeeGID),
              operation.newPayeeKey == nil,
              operation.newPayeeName == nil else {
            throw HostError.message(
                "transaction \(operation.transactionGID) has an incomplete or mixed payee target"
            )
        }
    } else {
        guard let newPayeeKey = operation.newPayeeKey,
              let newPayeeName = operation.newPayeeName,
              !isBlank(newPayeeKey),
              !isBlank(newPayeeName) else {
            throw HostError.message(
                "transaction \(operation.transactionGID) has an incomplete or mixed payee target"
            )
        }
    }
}

func validateOperations(_ operations: [WriterOperation], policy: WriterPolicy) throws {
    var transactionGIDs: Set<String> = []
    var newPayeeNames: [String: String] = [:]
    for operation in operations {
        try validateOperation(operation, policy: policy)
        guard transactionGIDs.insert(operation.transactionGID).inserted else {
            throw HostError.message(
                "transaction GID \(operation.transactionGID) appears more than once"
            )
        }
        if let key = operation.newPayeeKey, let name = operation.newPayeeName {
            if let previousName = newPayeeNames[key], previousName != name {
                throw HostError.message("new payee key \(key) maps to inconsistent names")
            }
            newPayeeNames[key] = name
        }
    }
}

func validateWriterPlan(_ plan: WriterPlan) throws -> String {
    let policy = supportedWriterPolicy
    guard plan.contractVersion == 1,
          plan.profileID == policy.profileID,
          plan.modelChecksum == policy.modelChecksum,
          plan.capability == policy.capability,
          plan.schemaVersion == policy.schemaVersion else {
        throw HostError.message("unsupported or incomplete Core Data writer contract")
    }
    guard !plan.operations.isEmpty else {
        throw HostError.message("reassignment writer plan must contain at least one operation")
    }
    guard plan.payeeMerges == nil else {
        throw HostError.message("reassignment writer plan must not contain payee merges")
    }
    try validateOperations(plan.operations, policy: policy)
    return policy.modelChecksum
}

func requireMoneyWizStopped(
    isRunning: (String) throws -> Bool
) throws {
    do {
        for bundleIdentifier in moneyWizBundleIdentifiers
            where try isRunning(bundleIdentifier) {
            throw HostError.message(
                "Quit MoneyWiz 2026 before applying a Core Data writer plan"
            )
        }
    } catch let error as HostError {
        throw error
    } catch {
        throw HostError.message(
            "cannot verify whether MoneyWiz 2026 is running: \(error.localizedDescription)"
        )
    }
}

func requireMoneyWizStopped() throws {
    try requireMoneyWizStopped { bundleIdentifier in
        !NSRunningApplication.runningApplications(
            withBundleIdentifier: bundleIdentifier
        ).isEmpty
    }
}

func validateExactModelChecksum(
    expected: String,
    store: String?,
    selectedModel: String
) throws {
    guard store == expected else {
        throw HostError.message("database store does not match the verified Core Data model checksum")
    }
    guard selectedModel == expected else {
        throw HostError.message("selected managed-object model does not match the verified checksum")
    }
}

func loadContainer(
    storeURL: URL,
    modelURL: URL,
    expectedChecksum: String,
    readOnly: Bool = false
) throws -> NSPersistentContainer {
    guard let model = NSManagedObjectModel(contentsOf: modelURL) else {
        throw HostError.message("cannot load MoneyWiz managed-object model at \(modelURL.path)")
    }
    let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
        ofType: NSSQLiteStoreType,
        at: storeURL,
        options: nil
    )
    try validateExactModelChecksum(
        expected: expectedChecksum,
        store: metadata[modelChecksumMetadataKey] as? String,
        selectedModel: model.versionChecksum
    )
    guard model.isConfiguration(withName: nil, compatibleWithStoreMetadata: metadata) else {
        throw HostError.message("MoneyWiz managed-object model is incompatible with the database store")
    }
    let container = NSPersistentContainer(name: "MoneyWizDataModel", managedObjectModel: model)
    let description = NSPersistentStoreDescription(url: storeURL)
    description.isReadOnly = readOnly
    description.shouldMigrateStoreAutomatically = false
    description.shouldInferMappingModelAutomatically = false
    description.setOption(true as NSNumber, forKey: NSPersistentHistoryTrackingKey)
    description.setOption(true as NSNumber, forKey: NSPersistentStoreRemoteChangeNotificationPostOptionKey)
    container.persistentStoreDescriptions = [description]

    let semaphore = DispatchSemaphore(value: 0)
    var loadError: Error?
    container.loadPersistentStores { _, error in
        loadError = error
        semaphore.signal()
    }
    semaphore.wait()
    if let loadError {
        throw HostError.message("cannot open MoneyWiz database: \(loadError.localizedDescription)")
    }
    return container
}

struct ResolvedWriterOperation {
    let operation: WriterOperation
    let transaction: NSManagedObject
    let transactionUser: NSManagedObject
    let existingPayee: NSManagedObject?
}

func preflightOperations(
    _ operations: [WriterOperation],
    context: NSManagedObjectContext
) throws -> [ResolvedWriterOperation] {
    var resolved: [ResolvedWriterOperation] = []
    var newPayeeUsers: [String: NSManagedObjectID] = [:]
    for operation in operations {
        let transaction = try fetchExactObject(
            entityName: operation.transactionEntity,
            gid: operation.transactionGID,
            context: context
        )
        guard let account = transaction.value(forKey: "account") as? NSManagedObject,
              let transactionUser = account.value(forKey: "user") as? NSManagedObject else {
            throw HostError.message(
                "transaction \(operation.transactionGID) has no account user for payee assignment"
            )
        }

        var existingPayee: NSManagedObject?
        if let existingPayeeGID = operation.existingPayeeGID {
            let payee = try fetchExactObject(
                entityName: "Payee", gid: existingPayeeGID, context: context
            )
            guard let payeeUser = payee.value(forKey: "user") as? NSManagedObject,
                  payeeUser.objectID == transactionUser.objectID else {
                throw HostError.message(
                    "transaction \(operation.transactionGID) and target payee must belong to the same user"
                )
            }
            existingPayee = payee
        } else if let key = operation.newPayeeKey {
            if let priorUser = newPayeeUsers[key], priorUser != transactionUser.objectID {
                throw HostError.message(
                    "new payee key \(key) resolved to more than one MoneyWiz user"
                )
            }
            newPayeeUsers[key] = transactionUser.objectID
        } else {
            throw HostError.message(
                "transaction \(operation.transactionGID) has no resolved payee target"
            )
        }
        resolved.append(
            ResolvedWriterOperation(
                operation: operation,
                transaction: transaction,
                transactionUser: transactionUser,
                existingPayee: existingPayee
            )
        )
    }
    return resolved
}

func mutateResolvedOperations(
    _ resolvedOperations: [ResolvedWriterOperation],
    context: NSManagedObjectContext
) throws -> WriterResult {
    var createdPayees: [String: NSManagedObject] = [:]
    for resolved in resolvedOperations {
        let operation = resolved.operation
        let targetPayee: NSManagedObject
        if let existingPayee = resolved.existingPayee {
            targetPayee = existingPayee
        } else {
            guard let key = operation.newPayeeKey,
                  let name = operation.newPayeeName else {
                throw HostError.message(
                    "transaction \(operation.transactionGID) lost its preflighted payee target"
                )
            }
            if let createdPayee = createdPayees[key] {
                targetPayee = createdPayee
            } else {
                let payee = NSEntityDescription.insertNewObject(
                    forEntityName: "Payee", into: context
                )
                payee.setValue(
                    UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
                    forKey: "GID"
                )
                payee.setValue(name, forKey: "name")
                payee.setValue(Date(), forKey: "objectCreationDate")
                payee.setValue(resolved.transactionUser, forKey: "user")
                createdPayees[key] = payee
                targetPayee = payee
            }
        }
        resolved.transaction.setValue(targetPayee, forKey: "payee")
    }
    if context.hasChanges {
        try context.save()
    }
    return WriterResult(
        createdPayees: createdPayees.count,
        reassignedTransactions: resolvedOperations.count,
        mergedPayees: 0,
        migratedRelationships: 0
    )
}

func writePlan(_ plan: WriterPlan, container: NSPersistentContainer) throws -> WriterResult {
    _ = try validateWriterPlan(plan)
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<WriterResult, Error> = .failure(HostError.message("writer did not run"))

    context.performAndWait {
        do {
            let resolvedOperations = try preflightOperations(
                plan.operations,
                context: context
            )
            result = .success(
                try mutateResolvedOperations(resolvedOperations, context: context)
            )
        } catch {
            context.rollback()
            result = .failure(error)
        }
    }
    return try result.get()
}

// Contract v2 is deliberately a narrow bridge over the independently verified v1
// payee assignment primitive.  The P1 transaction operation kinds are represented
// by their own capability contracts, but are not executable here.
struct WriterPlanV2: Decodable {
    let contractVersion: Int
    let operationSchemaVersion: Int
    let planID: String
    let planDigest: String
    let profileID: String
    let modelChecksum: String
    let storeIdentity: StoreIdentity
    let ownerURI: String
    let appIdentity: AppIdentity
    let capability: String
    let createdAt: String
    let timezone: String
    let sourceInterval: SourceInterval
    let sourceEvidenceReferences: [String]
    let expectedAccountGID: String
    let expectedCachedAccountBalance: String
    let currencyUnit: String
    let sourceEventID: String
    let operations: [WriterOperationV2]

    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version"
        case operationSchemaVersion = "operation_schema_version"
        case planID = "plan_id"
        case planDigest = "plan_digest"
        case profileID = "profile_id"
        case modelChecksum = "model_checksum"
        case storeIdentity = "store_identity"
        case ownerURI = "owner_uri"
        case appIdentity = "app_identity"
        case capability
        case createdAt = "created_at"
        case timezone
        case sourceInterval = "source_interval"
        case sourceEvidenceReferences = "source_evidence_refs"
        case expectedAccountGID = "expected_account_gid"
        case expectedCachedAccountBalance = "expected_cached_account_balance"
        case currencyUnit = "currency_unit"
        case sourceEventID = "source_event_id"
        case operations
    }
}

struct StoreIdentity: Decodable {
    let storeUUID: String

    enum CodingKeys: String, CodingKey { case storeUUID = "store_uuid" }
}

struct AppIdentity: Decodable {
    let bundleID: String
    let version: String
    let path: String
    let modelPath: String

    enum CodingKeys: String, CodingKey {
        case bundleID = "bundle_id"
        case version
        case path
        case modelPath = "model_path"
    }
}

struct SourceInterval: Decodable {
    let start: String
    let end: String
}

struct WriterOperationV2: Decodable {
    let operationID: String
    let kind: String
    let capability: String
    let transactionEntity: String
    let transactionGID: String
    let expectedOldPayeeGID: String?
    let targetPayeeGID: String?
    let ownerURI: String
    let sourceEventID: String
    let expectedPostcondition: PayeePostcondition?
    let allowedChangedFields: [String]?
    // W01 creation fields.  They remain optional at decode time because the same
    // v2 envelope also carries the already-shipped reassignment operation.
    let accountGID: String?
    let amount: String?
    let currencyUnit: String?
    let occurredAt: String?
    let timezone: String?
    let payeeGID: String?
    let categorySplits: [CategorySplit]?
    let tagGIDs: [String]?
    let note: String?
    let refundReference: RefundReference?
    let expectedBalanceDelta: String?

    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id"
        case kind
        case capability
        case transactionEntity = "transaction_entity"
        case transactionGID = "transaction_gid"
        case expectedOldPayeeGID = "expected_old_payee_gid"
        case targetPayeeGID = "target_payee_gid"
        case ownerURI = "owner_uri"
        case sourceEventID = "source_event_id"
        case expectedPostcondition = "expected_postcondition"
        case allowedChangedFields = "allowed_changed_fields"
        case accountGID = "account_gid"
        case amount
        case currencyUnit = "currency_unit"
        case occurredAt = "occurred_at"
        case timezone
        case payeeGID = "payee_gid"
        case categorySplits = "category_splits"
        case tagGIDs = "tag_gids"
        case note
        case refundReference = "refund_reference"
        case expectedBalanceDelta = "expected_balance_delta"
    }
}

struct CategorySplit: Codable, Equatable {
    let categoryGID: String
    let amount: String

    enum CodingKeys: String, CodingKey { case categoryGID = "category_gid"; case amount }
}

struct RefundReference: Codable, Equatable {
    let originalTransactionEntity: String
    let originalTransactionGID: String

    enum CodingKeys: String, CodingKey {
        case originalTransactionEntity = "original_transaction_entity"
        case originalTransactionGID = "original_transaction_gid"
    }
}

struct PayeePostcondition: Decodable {
    let payeeGID: String?

    enum CodingKeys: String, CodingKey { case payeeGID = "payee_gid" }
}

struct WriterOperationResultV2: Encodable {
    let operationID: String
    let status: String
    let transactionEntity: String
    let transactionGID: String
    let durableURI: String?
    let durableNumericID: String?
    let oldPayeeGID: String?
    let newPayeeGID: String?
    let postcondition: CreateTransactionPostconditionV2?

    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id"
        case status
        case transactionEntity = "transaction_entity"
        case transactionGID = "transaction_gid"
        case durableURI = "durable_uri"
        case durableNumericID = "durable_numeric_id"
        case oldPayeeGID = "old_payee_gid"
        case newPayeeGID = "new_payee_gid"
        case postcondition
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(operationID, forKey: .operationID)
        try container.encode(status, forKey: .status)
        try container.encode(transactionEntity, forKey: .transactionEntity)
        try container.encode(transactionGID, forKey: .transactionGID)
        try container.encode(durableURI, forKey: .durableURI)
        try container.encode(durableNumericID, forKey: .durableNumericID)
        try container.encode(oldPayeeGID, forKey: .oldPayeeGID)
        try container.encode(newPayeeGID, forKey: .newPayeeGID)
        try container.encodeIfPresent(postcondition, forKey: .postcondition)
    }
}

struct CreateTransactionPostconditionV2: Encodable {
    let transactionEntity: String
    let transactionGID: String
    let accountGID: String
    let ownerURI: String
    let amount: String
    let currencyUnit: String
    let occurredAt: String
    let timezone: String
    let payeeGID: String?
    let categorySplits: [CategorySplit]
    let tagGIDs: [String]
    let note: String?
    let refundReference: RefundReference?
    let expectedBalanceDelta: String

    enum CodingKeys: String, CodingKey {
        case transactionEntity = "transaction_entity", transactionGID = "transaction_gid"
        case accountGID = "account_gid", ownerURI = "owner_uri", amount, currencyUnit = "currency_unit"
        case occurredAt = "occurred_at", timezone, payeeGID = "payee_gid", categorySplits = "category_splits"
        case tagGIDs = "tag_gids", note, refundReference = "refund_reference"
        case expectedBalanceDelta = "expected_balance_delta"
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(transactionEntity, forKey: .transactionEntity)
        try c.encode(transactionGID, forKey: .transactionGID)
        try c.encode(accountGID, forKey: .accountGID)
        try c.encode(ownerURI, forKey: .ownerURI)
        try c.encode(amount, forKey: .amount)
        try c.encode(currencyUnit, forKey: .currencyUnit)
        try c.encode(occurredAt, forKey: .occurredAt)
        try c.encode(timezone, forKey: .timezone)
        try c.encode(payeeGID, forKey: .payeeGID)
        try c.encode(categorySplits, forKey: .categorySplits)
        try c.encode(tagGIDs, forKey: .tagGIDs)
        try c.encode(note, forKey: .note)
        try c.encode(refundReference, forKey: .refundReference)
        try c.encode(expectedBalanceDelta, forKey: .expectedBalanceDelta)
    }

}

struct WriterResultV2: Encodable {
    let contractVersion: Int
    let planID: String
    let planDigest: String
    let classification: String
    let verified: Bool
    let operations: [WriterOperationResultV2]

    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version"
        case planID = "plan_id"
        case planDigest = "plan_digest"
        case classification
        case verified
        case operations
    }
}

func canonicalV2Digest(_ rawPlan: [String: Any]) throws -> String {
    var digestInput = rawPlan
    digestInput.removeValue(forKey: "plan_digest")
    guard JSONSerialization.isValidJSONObject(digestInput) else {
        throw HostError.message("writer v2 plan is not a JSON object")
    }
    let data = try JSONSerialization.data(
        withJSONObject: digestInput, options: [.sortedKeys, .withoutEscapingSlashes]
    )
    return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

func validateWriterPlanV2(_ plan: WriterPlanV2, rawPlan: [String: Any]) throws {
    let policy = supportedWriterPolicy
    let requiredKeys: Set<String> = [
        "contract_version", "operation_schema_version", "plan_id", "plan_digest", "profile_id",
        "model_checksum", "store_identity", "owner_uri", "app_identity", "capability", "created_at",
        "timezone", "source_interval", "source_evidence_refs", "expected_account_gid",
        "expected_cached_account_balance", "currency_unit", "source_event_id", "operations",
    ]
    guard Set(rawPlan.keys) == requiredKeys else {
        throw HostError.message("writer v2 plan contains unknown or missing fields")
    }
    let nestedKeys: [(String, Set<String>)] = [
        ("store_identity", ["store_uuid"]),
        ("app_identity", ["bundle_id", "version", "path", "model_path"]),
        ("source_interval", ["start", "end"]),
    ]
    for (key, expectedKeys) in nestedKeys {
        guard let object = rawPlan[key] as? [String: Any], Set(object.keys) == expectedKeys else {
            throw HostError.message("writer v2 \(key) contains unknown or missing fields")
        }
    }
    let operationKeys: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "expected_old_payee_gid", "target_payee_gid", "owner_uri", "source_event_id",
        "expected_postcondition", "allowed_changed_fields",
    ]
    guard let rawOperations = rawPlan["operations"] as? [[String: Any]] else {
        throw HostError.message("writer v2 operations must be JSON objects")
    }
    for rawOperation in rawOperations {
        let kind = rawOperation["kind"] as? String
        if kind == "create_income" || kind == "create_expense" || kind == "create_refund" {
            try validateCreationOperationShape(rawOperation, plan: plan)
            continue
        }
        guard Set(rawOperation.keys) == operationKeys,
              let postcondition = rawOperation["expected_postcondition"] as? [String: Any],
              Set(postcondition.keys) == ["payee_gid"] else {
            throw HostError.message("writer v2 operation contains unknown or missing fields")
        }
    }
    guard plan.contractVersion == 2,
          plan.operationSchemaVersion == 1,
          plan.profileID == policy.profileID,
          plan.modelChecksum == policy.modelChecksum,
          (plan.capability == policy.capability || ["write.create-income", "write.create-expense", "write.create-refund"].contains(plan.capability)),
          moneyWizBundleIdentifiers.contains(plan.appIdentity.bundleID),
          !isBlank(plan.appIdentity.version),
          !isBlank(plan.appIdentity.path),
          !isBlank(plan.appIdentity.modelPath),
          !isBlank(plan.planID),
          !isBlank(plan.storeIdentity.storeUUID),
          !isBlank(plan.ownerURI),
          !isBlank(plan.createdAt),
          !isBlank(plan.timezone),
          !isBlank(plan.sourceInterval.start),
          !isBlank(plan.sourceInterval.end),
          !isBlank(plan.expectedAccountGID),
          !isBlank(plan.expectedCachedAccountBalance),
          !isBlank(plan.currencyUnit),
          !isBlank(plan.sourceEventID),
          !plan.sourceEvidenceReferences.isEmpty,
          !plan.operations.isEmpty else {
        throw HostError.message("unsupported or incomplete Core Data writer v2 contract")
    }
    _ = try decimalValue(plan.expectedCachedAccountBalance, field: "expected cached account balance")
    _ = try planTimestamp(plan.createdAt)
    let start = try planTimestamp(plan.sourceInterval.start)
    let end = try planTimestamp(plan.sourceInterval.end)
    guard start <= end, TimeZone(identifier: plan.timezone) != nil else {
        throw HostError.message("writer v2 timestamps, timezone, or decimal guard is invalid")
    }
    let calculatedDigest = try canonicalV2Digest(rawPlan)
    guard plan.planDigest == calculatedDigest else {
        throw HostError.message("writer v2 plan digest does not match reviewed payload")
    }
    var operationIDs: Set<String> = []
    var transactionGIDs: Set<String> = []
    let creationKinds = Set(["create_income", "create_expense", "create_refund"])
    let creationCount = plan.operations.filter { creationKinds.contains($0.kind) }.count
    if creationCount > 0 && creationCount != plan.operations.count || creationCount > 1 {
        throw HostError.message("writer v2 creation plans must contain exactly one homogeneous operation")
    }
    for operation in plan.operations {
        if ["create_income", "create_expense", "create_refund"].contains(operation.kind) {
            guard operation.capability == plan.capability,
                  operation.accountGID == plan.expectedAccountGID,
                  operation.currencyUnit == plan.currencyUnit,
                  operation.timezone == plan.timezone,
                  operation.ownerURI == plan.ownerURI,
                  operation.sourceEventID == plan.sourceEventID else {
                throw HostError.message("writer v2 creation operation does not match its envelope")
            }
            guard operation.transactionGID == deterministicCreationGID(plan: plan) else {
                throw HostError.message("writer v2 creation GID is not the deterministic source-event identity")
            }
            guard operationIDs.insert(operation.operationID).inserted,
                  transactionGIDs.insert(operation.transactionGID).inserted else {
                throw HostError.message("writer v2 operation identifiers and transaction GIDs must be unique")
            }
            continue
        }
        guard operation.kind == "reassign_payee",
              plan.capability == policy.capability,
              operation.capability == policy.capability,
              policy.transactionEntities.contains(operation.transactionEntity),
              !isBlank(operation.operationID),
              !isBlank(operation.transactionGID),
              let targetPayeeGID = operation.targetPayeeGID,
              !isBlank(targetPayeeGID),
              !isBlank(operation.ownerURI),
              !isBlank(operation.sourceEventID),
              operation.sourceEventID == plan.sourceEventID,
              operation.expectedPostcondition?.payeeGID == operation.targetPayeeGID,
              operation.allowedChangedFields == ["payee"] else {
            throw HostError.message("writer v2 operation is unsupported or incomplete")
        }
        if let expectedOldPayeeGID = operation.expectedOldPayeeGID,
           isBlank(expectedOldPayeeGID) {
            throw HostError.message("writer v2 expected old payee GID must be nonblank or null")
        }
        guard operationIDs.insert(operation.operationID).inserted,
              transactionGIDs.insert(operation.transactionGID).inserted else {
            throw HostError.message("writer v2 operation identifiers and transaction GIDs must be unique")
        }
    }
}

func deterministicCreationGID(plan: WriterPlanV2) -> String {
    let identity: [String: String] = [
        "owner_uri": plan.ownerURI,
        "source_event_id": plan.sourceEventID,
        "store_uuid": plan.storeIdentity.storeUUID,
    ]
    let data = try! JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys, .withoutEscapingSlashes])
    let bytes = Array(SHA256.hash(data: data).prefix(16))
    let hex = bytes.map { String(format: "%02X", $0) }.joined()
    return "\(hex.prefix(8))-\(hex.dropFirst(8).prefix(4))-\(hex.dropFirst(12).prefix(4))-\(hex.dropFirst(16).prefix(4))-\(hex.dropFirst(20).prefix(12))"
}

func validateCreationOperationShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "account_gid", "owner_uri", "source_event_id", "amount", "currency_unit",
        "occurred_at", "timezone", "payee_gid", "category_splits", "tag_gids", "note",
        "refund_reference", "expected_balance_delta", "expected_postcondition",
    ]
    guard Set(raw.keys) == required,
          let kind = raw["kind"] as? String,
          let capability = raw["capability"] as? String,
          let entity = raw["transaction_entity"] as? String,
          let amount = raw["amount"] as? String,
          let delta = raw["expected_balance_delta"] as? String,
          let occurredAt = raw["occurred_at"] as? String,
          let splits = raw["category_splits"] as? [[String: Any]],
          let tags = raw["tag_gids"] as? [String],
          raw["payee_gid"] is String || raw["payee_gid"] is NSNull,
          raw["note"] is String || raw["note"] is NSNull,
          let postcondition = raw["expected_postcondition"] as? [String: Any],
          Set(postcondition.keys) == required.subtracting(["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"]),
          postcondition["transaction_entity"] as? String == entity,
          postcondition["transaction_gid"] as? String == raw["transaction_gid"] as? String,
          postcondition["amount"] as? String == amount,
          postcondition["expected_balance_delta"] as? String == delta else {
        throw HostError.message("writer v2 creation operation contains unknown, missing, or unreviewed fields")
    }
    let expectedPost = raw.filter { !["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"].contains($0.key) }
    guard NSDictionary(dictionary: postcondition).isEqual(to: expectedPost) else {
        throw HostError.message("W01 postcondition differs from reviewed fields")
    }
    for field in ["operation_id", "transaction_gid", "account_gid", "owner_uri", "source_event_id", "currency_unit", "timezone"] {
        guard let value = raw[field] as? String, !isBlank(value), value == value.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw HostError.message("W01 identity text must be trimmed and nonblank")
        }
    }
    for field in ["payee_gid", "note"] {
        if let value = raw[field] as? String, isBlank(value) || value != value.trimmingCharacters(in: .whitespacesAndNewlines) {
            throw HostError.message("W01 optional text must be trimmed and nonblank")
        }
    }
    guard plan.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
          !occurredAt.contains("."), !plan.createdAt.contains(".") else {
        throw HostError.message("W01 requires canonical currency and whole-second timestamps")
    }
    let instant = try planTimestamp(occurredAt)
    let offset: Int
    if occurredAt.hasSuffix("Z") { offset = 0 }
    else {
        let suffix = String(occurredAt.suffix(6))
        guard let hours = Int(suffix.dropFirst().prefix(2)), let minutes = Int(suffix.suffix(2)) else {
            throw HostError.message("W01 invalid timestamp offset")
        }
        offset = (hours * 60 + minutes) * 60 * (suffix.first == "-" ? -1 : 1)
    }
    guard TimeZone(identifier: plan.timezone)?.secondsFromGMT(for: instant) == offset else {
        throw HostError.message("W01 timestamp offset differs from timezone")
    }
    func canonicalDecimal(_ value: String) throws -> Decimal {
        let parsed = try decimalValue(value, field: "creation amount")
        guard NSDecimalNumber(decimal: parsed).stringValue == value else {
            throw HostError.message("W01 amounts must be canonical Decimal text")
        }
        return parsed
    }
    let mappings = [
        "create_income": ("write.create-income", "DepositTransaction", 1),
        "create_expense": ("write.create-expense", "WithdrawTransaction", -1),
        "create_refund": ("write.create-refund", "RefundTransaction", 1),
    ]
    let parsedAmount = try canonicalDecimal(amount)
    let parsedDelta = try canonicalDecimal(delta)
    guard let mapping = mappings[kind], capability == mapping.0, entity == mapping.1,
          capability == plan.capability, !isBlank(occurredAt),
          parsedAmount * Decimal(mapping.2) > 0, parsedDelta == parsedAmount else {
        throw HostError.message("writer v2 creation kind, amount, or capability is invalid")
    }
    _ = try planTimestamp(occurredAt)
    var categoryGIDs: Set<String> = []
    var total = Decimal.zero
    for split in splits {
        guard Set(split.keys) == ["category_gid", "amount"], let gid = split["category_gid"] as? String,
              !isBlank(gid), categoryGIDs.insert(gid).inserted, let splitAmount = split["amount"] as? String else {
            throw HostError.message("writer v2 category split is invalid")
        }
        let value = try canonicalDecimal(splitAmount)
        guard value * parsedAmount > 0, gid == gid.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw HostError.message("W01 category split sign or identity is invalid")
        }
        total += value
    }
    let transactionAmount = try decimalValue(amount, field: "creation amount")
    if !splits.isEmpty && total != transactionAmount {
        throw HostError.message("writer v2 category split total does not equal transaction amount")
    }
    guard Set(tags).count == tags.count, tags == tags.sorted(),
          tags.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: .whitespacesAndNewlines) }),
          splits.compactMap({ $0["category_gid"] as? String }) == categoryGIDs.sorted() else {
        throw HostError.message("writer v2 tags must be unique nonblank GIDs")
    }
    let refund = raw["refund_reference"]
    if kind == "create_refund" {
        guard let reference = refund as? [String: Any], Set(reference.keys) == ["original_transaction_entity", "original_transaction_gid"],
              reference["original_transaction_entity"] as? String == "WithdrawTransaction",
              let gid = reference["original_transaction_gid"] as? String, !isBlank(gid) else {
            throw HostError.message("writer v2 refund requires one explicit withdraw reference")
        }
    } else if !(refund is NSNull) {
        throw HostError.message("writer v2 refund reference is unsupported for this kind")
    }
}

func payeeGID(_ transaction: NSManagedObject) -> String? {
    let payee = transaction.value(forKey: "payee") as? NSManagedObject
    return payee?.value(forKey: "GID") as? String
}

func durableNumericID(_ objectID: NSManagedObjectID) -> String {
    let reference = objectID.uriRepresentation().lastPathComponent
    guard reference.first == "p", reference.dropFirst().allSatisfy({ $0.isNumber }) else {
        return ""
    }
    return String(reference.dropFirst())
}

func classifyRecoveryStates(_ states: [(expectedOld: String?, target: String, actual: String?)]) -> String {
    guard !states.isEmpty else { return "unknown" }
    if states.allSatisfy({ $0.actual == $0.target }) { return "noop" }
    if states.allSatisfy({ $0.actual == $0.expectedOld }) { return "retry_safe" }
    return "unknown"
}

func decimalValue(_ value: String, field: String) throws -> Decimal {
    guard value.range(of: #"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"#, options: .regularExpression) != nil,
          let decimal = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")),
          let native = Double(value), native.isFinite,
          Decimal(string: String(native), locale: Locale(identifier: "en_US_POSIX")) == decimal else {
        throw HostError.message("writer v2 \(field) must be a plain Decimal string")
    }
    return decimal
}

func planTimestamp(_ value: String) throws -> Date {
    guard value.range(of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"#, options: .regularExpression) != nil else {
        throw HostError.message("writer v2 timestamp must have seconds and an explicit offset")
    }
    let formatter = ISO8601DateFormatter()
    if value.contains(".") { formatter.formatOptions.insert(.withFractionalSeconds) }
    guard let result = formatter.date(from: value) else {
        throw HostError.message("writer v2 timestamp is invalid")
    }
    // ISO8601DateFormatter normalizes impossible dates. Compare original wall-clock
    // components to the parsed instant to reject rollovers and leap-second aliases.
    let fields = value.prefix(19).split(whereSeparator: { "-T:".contains($0) }).compactMap { Int($0) }
    var offset = 0
    if !value.hasSuffix("Z") {
        let suffix = value.suffix(6)
        guard let hours = Int(suffix.dropFirst().prefix(2)), let minutes = Int(suffix.suffix(2)),
              hours < 24, minutes < 60 else { throw HostError.message("writer v2 timestamp offset is invalid") }
        offset = (hours * 60 + minutes) * 60 * (suffix.first == "-" ? -1 : 1)
    }
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0)!
    let components = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second],
        from: result.addingTimeInterval(TimeInterval(offset)))
    guard fields.count == 6,
          fields == [components.year!, components.month!, components.day!, components.hour!, components.minute!, components.second!] else {
        throw HostError.message("writer v2 timestamp has invalid calendar components")
    }
    return result
}

func validateAccountGuards(_ account: NSManagedObject, plan: WriterPlanV2) throws {
    guard let accountGID = account.value(forKey: "GID") as? String,
          accountGID == plan.expectedAccountGID else {
        throw HostError.message("writer v2 transaction account does not match plan account")
    }
    let expectedBalance = try decimalValue(
        plan.expectedCachedAccountBalance, field: "expected cached account balance"
    )
    guard let rawBalance = account.value(forKey: "ballance") as? NSNumber else {
        throw HostError.message("writer v2 account lacks the verified ballance guard attribute")
    }
    guard rawBalance.doubleValue.isFinite,
          let actualBalance = Decimal(string: String(rawBalance.doubleValue)),
          actualBalance == expectedBalance else {
        throw HostError.message("writer v2 account balance is stale")
    }
    guard account.entity.attributesByName["currencyName"] != nil,
          let currencyUnit = account.value(forKey: "currencyName") as? String,
          currencyUnit == plan.currencyUnit else {
        throw HostError.message("writer v2 account currency does not match plan currency unit")
    }
}

func immutableTransactionFingerprint(_ transaction: NSManagedObject) throws -> [String: NSObject] {
    var fingerprint: [String: NSObject] = [:]
    for name in transaction.entity.attributesByName.keys {
        guard let value = transaction.value(forKey: name) else {
            fingerprint["attribute:\(name)"] = NSNull()
            continue
        }
        guard let object = value as? NSObject, let copyable = object as? NSCopying,
              let snapshot = copyable.copy(with: nil) as? NSObject else {
            throw HostError.message("cannot independently snapshot transaction attribute \(name)")
        }
        fingerprint["attribute:\(name)"] = snapshot
    }
    for (name, relationship) in transaction.entity.relationshipsByName where name != "payee" {
        let value = transaction.value(forKey: name)
        if relationship.isToMany {
            let objects: [NSManagedObject]
            if let ordered = value as? NSOrderedSet {
                objects = ordered.array.compactMap { $0 as? NSManagedObject }
                guard objects.count == ordered.count else { throw HostError.message("invalid ordered relationship") }
            } else if let unordered = value as? Set<NSManagedObject> {
                objects = unordered.sorted { $0.objectID.uriRepresentation().absoluteString < $1.objectID.uriRepresentation().absoluteString }
            } else if value == nil { objects = [] }
            else { throw HostError.message("cannot snapshot transaction relationship \(name)") }
            fingerprint["relationship:\(name)"] = objects.map { $0.objectID.uriRepresentation().absoluteString } as NSArray
        } else if let related = value as? NSManagedObject {
            fingerprint["relationship:\(name)"] = related.objectID.uriRepresentation().absoluteString as NSString
        } else if value == nil {
            fingerprint["relationship:\(name)"] = NSNull()
        } else { throw HostError.message("cannot snapshot transaction relationship \(name)") }
    }
    return fingerprint
}

func resolveV2References(
    _ operation: WriterOperationV2, plan: WriterPlanV2, context: NSManagedObjectContext
) throws -> (transaction: NSManagedObject, target: NSManagedObject) {
    let transaction = try fetchExactObject(
        entityName: operation.transactionEntity, gid: operation.transactionGID, context: context
    )
    guard let account = transaction.value(forKey: "account") as? NSManagedObject,
          let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          operation.ownerURI == plan.ownerURI else {
        throw HostError.message("writer v2 transaction owner does not match plan owner")
    }
    try validateAccountGuards(account, plan: plan)
    guard let targetGID = operation.targetPayeeGID else {
        throw HostError.message("writer v2 payee operation lacks target payee")
    }
    let target = try fetchExactObject(entityName: "Payee", gid: targetGID, context: context)
    guard let targetOwner = target.value(forKey: "user") as? NSManagedObject,
          targetOwner.objectID == owner.objectID else {
        throw HostError.message("writer v2 target payee owner does not match transaction owner")
    }
    return (transaction, target)
}

func recoverPlanV2(_ plan: WriterPlanV2, container: NSPersistentContainer) throws -> WriterResultV2 {
    let context = container.newBackgroundContext()
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("writer v2 recovery did not run"))
    context.performAndWait {
        do {
            if let creation = plan.operations.first, creation.kind.hasPrefix("create_") {
                result = .success(try inspectCreation(creation, plan: plan, context: context))
                return
            }
            var recovered: [(WriterOperationV2, NSManagedObject, String?)] = []
            for operation in plan.operations {
                let (transaction, _) = try resolveV2References(operation, plan: plan, context: context)
                recovered.append((operation, transaction, payeeGID(transaction)))
            }
            let classification = classifyRecoveryStates(recovered.map {
                (expectedOld: $0.0.expectedOldPayeeGID, target: $0.0.targetPayeeGID!, actual: $0.2)
            })
            let status = classification == "noop" ? "noop" : "unknown"
            result = .success(WriterResultV2(
                contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
                classification: classification, verified: classification == "noop",
                operations: recovered.map { operation, transaction, actual in
                    WriterOperationResultV2(
                        operationID: operation.operationID, status: status,
                        transactionEntity: operation.transactionEntity, transactionGID: operation.transactionGID,
                        durableURI: transaction.objectID.uriRepresentation().absoluteString,
                        durableNumericID: durableNumericID(transaction.objectID), oldPayeeGID: actual,
                        newPayeeGID: actual, postcondition: nil
                    )
                }
            ))
        } catch { result = .failure(error) }
    }
    return try result.get()
}

func writePlanV2(
    _ plan: WriterPlanV2,
    container: NSPersistentContainer,
    requireStopped: () throws -> Void = requireMoneyWizStopped
) throws -> WriterResultV2 {
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("writer v2 did not run"))
    context.performAndWait {
        do {
            try requireStopped()
            if let creation = plan.operations.first,
               ["create_income", "create_expense", "create_refund"].contains(creation.kind) {
                result = .success(try createTransactionV2(creation, plan: plan, context: context, requireStopped: requireStopped))
                return
            }
            var resolved: [(WriterOperationV2, NSManagedObject, NSManagedObject, String?, [String: NSObject])] = []
            for operation in plan.operations {
                let (transaction, target) = try resolveV2References(operation, plan: plan, context: context)
                let oldPayee = payeeGID(transaction)
                resolved.append((operation, transaction, target, oldPayee, try immutableTransactionFingerprint(transaction)))
            }
            let recoveryClassification = classifyRecoveryStates(resolved.map {
                (expectedOld: $0.0.expectedOldPayeeGID, target: $0.0.targetPayeeGID!, actual: $0.3)
            })
            if recoveryClassification == "noop" {
                let noops = resolved.map { operation, transaction, _, oldPayee, _ in
                    WriterOperationResultV2(
                        operationID: operation.operationID, status: "noop",
                        transactionEntity: operation.transactionEntity, transactionGID: operation.transactionGID,
                        durableURI: transaction.objectID.uriRepresentation().absoluteString,
                        durableNumericID: durableNumericID(transaction.objectID), oldPayeeGID: oldPayee,
                        newPayeeGID: oldPayee, postcondition: nil
                    )
                }
                result = .success(WriterResultV2(
                    contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
                    classification: "noop", verified: true, operations: noops
                ))
                return
            }
            guard recoveryClassification == "retry_safe" else {
                throw HostError.message("writer v2 recovery state is mixed or unknown; refusing replay")
            }
            // The second process check narrows the external-app race immediately before save.
            try requireStopped()
            for (_, transaction, target, _, _) in resolved {
                transaction.setValue(target, forKey: "payee")
            }
#if MONEYWIZ_TOOLS_TESTING
            if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
            if context.hasChanges { try context.save() }
#if MONEYWIZ_TOOLS_TESTING
            if writerTestCrashPoint == .afterSave { _exit(87) }
#endif

            let readback = container.newBackgroundContext()
            var operationResults: [WriterOperationResultV2] = []
            var readbackError: Error?
            readback.performAndWait {
                do {
                    for (operation, _, _, oldPayee, preimage) in resolved {
                        let persisted = try fetchExactObject(
                            entityName: operation.transactionEntity, gid: operation.transactionGID, context: readback
                        )
                        let actualPayee = payeeGID(persisted)
                        guard actualPayee == operation.expectedPostcondition?.payeeGID else {
                            throw HostError.message("writer v2 persisted read-back failed for \(operation.transactionGID)")
                        }
                        guard try immutableTransactionFingerprint(persisted) == preimage else {
                            throw HostError.message("writer v2 changed fields outside the reviewed payee assignment")
                        }
                        guard let persistedAccount = persisted.value(forKey: "account") as? NSManagedObject else {
                            throw HostError.message("writer v2 persisted account is missing")
                        }
                        try validateAccountGuards(persistedAccount, plan: plan)
                        operationResults.append(WriterOperationResultV2(
                            operationID: operation.operationID, status: "applied",
                            transactionEntity: operation.transactionEntity, transactionGID: operation.transactionGID,
                            durableURI: persisted.objectID.uriRepresentation().absoluteString,
                            durableNumericID: durableNumericID(persisted.objectID), oldPayeeGID: oldPayee,
                            newPayeeGID: actualPayee, postcondition: nil
                        ))
                    }
                } catch { readbackError = error }
            }
            if let readbackError { throw readbackError }
            result = .success(WriterResultV2(
                contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
                classification: "applied", verified: true, operations: operationResults
            ))
        } catch {
            context.rollback()
            result = .failure(error)
        }
    }
    return try result.get()
}

// Core Data Double setters must receive the same conversion used by plan validation.
// NSDecimalNumber.doubleValue takes a different rounding path for some small values.
func nativeDouble(_ value: Decimal) -> Double {
    Double(NSDecimalNumber(decimal: value).stringValue)!
}

func creationObjects(entity: String, gid: String, context: NSManagedObjectContext) throws -> [NSManagedObject] {
    let request = NSFetchRequest<NSManagedObject>(entityName: entity)
    request.predicate = NSPredicate(format: "GID == %@", gid)
    return try context.fetch(request)
}

func nativeDecimal(_ object: NSManagedObject, _ key: String) throws -> Decimal {
    guard let number = object.value(forKey: key) as? NSNumber, number.doubleValue.isFinite,
          let value = Decimal(string: String(number.doubleValue), locale: Locale(identifier: "en_US_POSIX")) else {
        throw HostError.message("W01 invalid native decimal \(key)")
    }
    return value
}

func relatedObjects(_ object: NSManagedObject, _ key: String) throws -> Set<NSManagedObject> {
    guard object.entity.relationshipsByName[key]?.isToMany == true,
          let result = object.value(forKey: key) as? Set<NSManagedObject> else {
        throw HostError.message("W01 missing or invalid relationship \(key)")
    }
    return result
}

func requireCreationFixture(_ coordinator: NSPersistentStoreCoordinator) throws {
    guard coordinator.persistentStores.count == 1,
          coordinator.metadata(for: coordinator.persistentStores[0])["MoneyWizToolsDisposableFixture"] as? String == "W01-v1" else {
        throw HostError.message("W01 live creation remains blocked; marked disposable fixture required")
    }
}

struct CreationReferences {
    let account: NSManagedObject
    let payee: NSManagedObject?
    let categories: [NSManagedObject]
    let tags: [NSManagedObject]
    let original: NSManagedObject?
    let amount: Decimal
    let balanceAfter: Decimal
}

func preflightCreation(_ operation: WriterOperationV2, plan: WriterPlanV2,
                       context: NSManagedObjectContext, alreadyPresent: Bool) throws -> CreationReferences {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W01 missing coordinator") }
    try requireCreationFixture(coordinator)
    let account = try fetchExactObject(entityName: "CashAccount", gid: plan.expectedAccountGID, context: context)
    guard account.entity.name == "CashAccount",
          let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          account.value(forKey: "currencyName") as? String == plan.currencyUnit,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil else {
        throw HostError.message("W01 requires an active, same-owner, same-currency disposable CashAccount")
    }
    let amount = try decimalValue(operation.amount!, field: "creation amount")
    let before = try decimalValue(plan.expectedCachedAccountBalance, field: "cached balance")
    let after = before + amount
    // Each operand being representable is insufficient: their sum must also survive Double.
    _ = try decimalValue(NSDecimalNumber(decimal: after).stringValue, field: "resulting balance")
    guard try nativeDecimal(account, "ballance") == (alreadyPresent ? after : before) else {
        throw HostError.message("W01 account balance is stale")
    }
    func owned(_ entity: String, _ gid: String) throws -> NSManagedObject {
        let object = try fetchExactObject(entityName: entity, gid: gid, context: context)
        guard (object.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID else {
            throw HostError.message("W01 \(entity) owner mismatch")
        }
        return object
    }
    let payee = try operation.payeeGID.map { try owned("Payee", $0) }
    let categories = try (operation.categorySplits ?? []).map { split -> NSManagedObject in
        let category = try owned("Category", split.categoryGID)
        let expectedType = operation.kind == "create_income" ? 2 : 1
        guard (category.value(forKey: "type") as? NSNumber)?.intValue == expectedType else {
            throw HostError.message("W01 category type does not match transaction kind")
        }
        return category
    }
    let tags = try (operation.tagGIDs ?? []).map { try owned("Tag", $0) }
    var original: NSManagedObject?
    if let reference = operation.refundReference {
        let withdrawal = try fetchExactObject(entityName: "WithdrawTransaction", gid: reference.originalTransactionGID, context: context)
        guard withdrawal.entity.name == "WithdrawTransaction",
              (withdrawal.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              withdrawal.value(forKey: "originalCurrency") as? String == plan.currencyUnit,
              try nativeDecimal(withdrawal, "amount") < 0,
              try nativeDecimal(withdrawal, "originalAmount") == nativeDecimal(withdrawal, "amount"),
              (withdrawal.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              (withdrawal.value(forKey: "status") as? NSNumber)?.intValue == 1,
              (withdrawal.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              withdrawal.value(forKey: "investmentHolding") == nil else {
            throw HostError.message("W01 refund requires an ordinary same-account withdrawal")
        }
        var refunded = Decimal.zero
        var seen: Set<NSManagedObjectID> = []
        for link in try relatedObjects(withdrawal, "refundTransactionsLinks") {
            guard let refund = link.value(forKey: "refundTransaction") as? NSManagedObject,
                  refund.entity.name == "RefundTransaction",
                  (refund.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
                  refund.value(forKey: "originalCurrency") as? String == plan.currencyUnit,
                  seen.insert(refund.objectID).inserted,
                  try relatedObjects(refund, "withdrawTransactionsLinks").count == 1 else {
                throw HostError.message("W01 existing refund graph is ambiguous")
            }
            let value = try nativeDecimal(refund, "amount")
            guard value > 0, try nativeDecimal(refund, "originalAmount") == value else {
                throw HostError.message("W01 existing refund amount is invalid")
            }
            refunded += value
        }
        let proposedTotal = refunded + (alreadyPresent ? 0 : amount)
        guard proposedTotal <= -(try nativeDecimal(withdrawal, "amount")) else {
            throw HostError.message("W01 refund total exceeds original withdrawal")
        }
        original = withdrawal
    }
    return CreationReferences(account: account, payee: payee, categories: categories, tags: tags,
                              original: original, amount: amount, balanceAfter: after)
}

// Verify requested fields, fixed native initialization, and every remaining attribute/relationship.
// Model defaults are evidence only for these explicitly disposable experiments.
func verifyCreatedTransaction(_ transaction: NSManagedObject, operation: WriterOperationV2,
                              plan: WriterPlanV2, references: CreationReferences) throws {
    let fixed: [String: Any] = [
        "GID": operation.transactionGID, "amount": nativeDouble(references.amount),
        "originalAmount": nativeDouble(references.amount), "originalCurrency": plan.currencyUnit,
        "originalExchangeRate": 1.0, "date": try planTimestamp(operation.occurredAt!),
        "objectCreationDate": try planTimestamp(plan.createdAt), "notes": operation.note as Any? ?? NSNull(),
    ]
    guard transaction.entity.name == operation.transactionEntity else { throw HostError.message("W01 source identity collision") }
    for (key, attribute) in transaction.entity.attributesByName {
        let expected = fixed[key] ?? attribute.defaultValue ?? NSNull()
        let actual = transaction.value(forKey: key) ?? NSNull()
        if attribute.attributeType == .doubleAttributeType, let number = expected as? NSNumber {
            guard try nativeDecimal(transaction, key) == Decimal(string: String(number.doubleValue)) else {
                throw HostError.message("W01 persisted decimal differs: \(key)")
            }
            continue
        }
        guard let expectedObject = expected as? NSObject, let actualObject = actual as? NSObject,
              actualObject.isEqual(expectedObject) else {
            throw HostError.message("W01 persisted attribute differs: \(key)")
        }
    }
    let scalarRefs: [String: NSManagedObject?] = ["account": references.account, "payee": references.payee]
    for (key, relationship) in transaction.entity.relationshipsByName {
        if let expected = scalarRefs[key] {
            guard (transaction.value(forKey: key) as? NSManagedObject)?.objectID == expected?.objectID else {
                throw HostError.message("W01 persisted reference differs: \(key)")
            }
        } else if key == "tags" {
            guard try relatedObjects(transaction, key) == Set(references.tags) else { throw HostError.message("W01 persisted tags differ") }
        } else if key == "categoriesAssigments" {
            let assignments = try relatedObjects(transaction, key)
            guard assignments.count == references.categories.count else { throw HostError.message("W01 persisted category count differs") }
            for (index, category) in references.categories.enumerated() {
                let matching = assignments.filter { ($0.value(forKey: "category") as? NSManagedObject)?.objectID == category.objectID }
                guard matching.count == 1, let assignment = matching.first,
                      try nativeDecimal(assignment, "amount") == decimalValue(operation.categorySplits![index].amount, field: "split"),
                      (assignment.value(forKey: "assigmentNumber") as? NSNumber)?.intValue == index,
                      assignment.value(forKey: "budget") == nil,
                      assignment.value(forKey: "scheduledTransacition") == nil,
                      assignment.value(forKey: "stringHistoryItem") == nil else {
                    throw HostError.message("W01 persisted category assignment differs")
                }
            }
        } else if key == "withdrawTransactionsLinks", let original = references.original {
            let links = try relatedObjects(transaction, key)
            guard links.count == 1, let link = links.first,
                  (link.value(forKey: "withdrawTransaction") as? NSManagedObject)?.objectID == original.objectID else {
                throw HostError.message("W01 persisted refund endpoint differs")
            }
        } else if relationship.isToMany {
            guard try relatedObjects(transaction, key).isEmpty else { throw HostError.message("W01 unexpected relationship: \(key)") }
        } else if transaction.value(forKey: key) != nil {
            throw HostError.message("W01 unexpected relationship: \(key)")
        }
    }
}

func creationReceipt(_ operation: WriterOperationV2, plan: WriterPlanV2, classification: String,
                     objectID: NSManagedObjectID?) -> WriterResultV2 {
    let success = classification == "applied" || classification == "noop"
    return WriterResultV2(contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
        classification: classification, verified: success, operations: [WriterOperationResultV2(
            operationID: operation.operationID, status: success ? classification : "unknown",
            transactionEntity: operation.transactionEntity, transactionGID: operation.transactionGID,
            durableURI: objectID?.uriRepresentation().absoluteString,
            durableNumericID: objectID.map(durableNumericID), oldPayeeGID: nil, newPayeeGID: nil,
            postcondition: success ? creationPostcondition(operation) : nil)])
}

func inspectCreation(_ operation: WriterOperationV2, plan: WriterPlanV2,
                     context: NSManagedObjectContext, saved: Bool = false) throws -> WriterResultV2 {
    let existing = try creationObjects(entity: "SyncObject", gid: operation.transactionGID, context: context)
    guard existing.count <= 1 else { throw HostError.message("W01 source identity is ambiguous") }
    let refs = try preflightCreation(operation, plan: plan, context: context, alreadyPresent: !existing.isEmpty)
    guard let transaction = existing.first else {
        guard !saved else { throw HostError.message("W01 persisted creation is missing") }
        return creationReceipt(operation, plan: plan, classification: "retry_safe", objectID: nil)
    }
    try verifyCreatedTransaction(transaction, operation: operation, plan: plan, references: refs)
    return creationReceipt(operation, plan: plan, classification: saved ? "applied" : "noop", objectID: transaction.objectID)
}

struct CreationPreimage {
    let objectID: NSManagedObjectID
    let fingerprint: [String: NSObject]
    let allowedKeys: Set<String>
}

func creationPreimages(_ refs: CreationReferences, context: NSManagedObjectContext) throws -> [CreationPreimage] {
    var results: [CreationPreimage] = []
    for name in ["SyncObject", "User", "CategoryAssigment", "WithdrawRefundTransactionLink"] {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: name)) {
            var allowed: Set<String> = []
            if object.objectID == refs.account.objectID { allowed = ["attribute:ballance", "relationship:transactionsHistory"] }
            if object.objectID == refs.payee?.objectID || refs.tags.contains(object) { allowed.insert("relationship:transactions") }
            if refs.categories.contains(object) { allowed.insert("relationship:categoryAssigments") }
            if object.objectID == refs.original?.objectID { allowed.insert("relationship:refundTransactionsLinks") }
            var fingerprint = try immutableTransactionFingerprint(object)
            // The shared payee helper intentionally excludes payee; creation preserves existing payees too.
            if object.entity.relationshipsByName["payee"] != nil {
                fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                    .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
            }
            results.append(CreationPreimage(objectID: object.objectID,
                fingerprint: fingerprint.filter { !allowed.contains($0.key) }, allowedKeys: allowed))
        }
    }
    return results
}

func verifyCreationPreimages(_ preimages: [CreationPreimage], context: NSManagedObjectContext) throws {
    for preimage in preimages {
        let object = try context.existingObject(with: preimage.objectID)
        var fingerprint = try immutableTransactionFingerprint(object)
        if object.entity.relationshipsByName["payee"] != nil {
            fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
        }
        guard fingerprint.filter({ !preimage.allowedKeys.contains($0.key) }) == preimage.fingerprint else {
            throw HostError.message("W01 modified an immutable or unrelated existing field")
        }
    }
}

func createTransactionV2(_ operation: WriterOperationV2, plan: WriterPlanV2,
                         context: NSManagedObjectContext,
                         requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let prior = try inspectCreation(operation, plan: plan, context: context)
    if prior.classification == "noop" { return prior }
    let refs = try preflightCreation(operation, plan: plan, context: context, alreadyPresent: false)
    let preimages = try creationPreimages(refs, context: context)
    // All references and numerical postconditions have been resolved before any insertion.
    let transaction = NSEntityDescription.insertNewObject(forEntityName: operation.transactionEntity, into: context)
    transaction.setValue(operation.transactionGID, forKey: "GID")
    transaction.setValue(nativeDouble(refs.amount), forKey: "amount")
    transaction.setValue(nativeDouble(refs.amount), forKey: "originalAmount")
    transaction.setValue(plan.currencyUnit, forKey: "originalCurrency")
    transaction.setValue(1.0, forKey: "originalExchangeRate")
    transaction.setValue(try planTimestamp(operation.occurredAt!), forKey: "date")
    transaction.setValue(try planTimestamp(plan.createdAt), forKey: "objectCreationDate")
    transaction.setValue(operation.note, forKey: "notes")
    transaction.setValue(refs.account, forKey: "account")
    transaction.setValue(refs.payee, forKey: "payee")
    transaction.setValue(NSSet(array: refs.tags), forKey: "tags")
    for (index, category) in refs.categories.enumerated() {
        let assignment = NSEntityDescription.insertNewObject(forEntityName: "CategoryAssigment", into: context)
        assignment.setValue(nativeDouble(try decimalValue(operation.categorySplits![index].amount, field: "split")), forKey: "amount")
        assignment.setValue(index, forKey: "assigmentNumber")
        assignment.setValue(category, forKey: "category")
        assignment.setValue(transaction, forKey: "transaction")
    }
    if let original = refs.original {
        let link = NSEntityDescription.insertNewObject(forEntityName: "WithdrawRefundTransactionLink", into: context)
        link.setValue(original, forKey: "withdrawTransaction")
        link.setValue(transaction, forKey: "refundTransaction")
    }
    refs.account.setValue(nativeDouble(refs.balanceAfter), forKey: "ballance")
    try requireStopped()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    // A new queue/context fetches objects from the persistent store, never from the mutation context.
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W01 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let receipt = try inspectCreation(operation, plan: plan, context: readback, saved: true)
            try verifyCreationPreimages(preimages, context: readback)
            return receipt
        }
    }
    return try result.get()
}

func creationPostcondition(_ operation: WriterOperationV2) -> CreateTransactionPostconditionV2 {
    CreateTransactionPostconditionV2(
        transactionEntity: operation.transactionEntity, transactionGID: operation.transactionGID,
        accountGID: operation.accountGID!, ownerURI: operation.ownerURI, amount: operation.amount!,
        currencyUnit: operation.currencyUnit!, occurredAt: operation.occurredAt!, timezone: operation.timezone!,
        payeeGID: operation.payeeGID, categorySplits: operation.categorySplits ?? [], tagGIDs: operation.tagGIDs ?? [],
        note: operation.note, refundReference: operation.refundReference,
        expectedBalanceDelta: operation.expectedBalanceDelta!
    )
}

func readModelChecksum(at modelURL: URL) throws -> String {
    configureTransformers()
    guard FileManager.default.fileExists(atPath: modelURL.path),
          let model = NSManagedObjectModel(contentsOf: modelURL) else {
        throw HostError.message("cannot load managed-object model")
    }
    // Attaching a model freezes it for a stable checksum; no store is opened.
    let coordinator = NSPersistentStoreCoordinator(managedObjectModel: model)
    return coordinator.managedObjectModel.versionChecksum
}

func storeIdentity(at storeURL: URL) throws -> String {
    let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
        ofType: NSSQLiteStoreType, at: storeURL, options: nil
    )
    guard let identity = metadata[NSStoreUUIDKey] as? String, !isBlank(identity) else {
        throw HostError.message("database store has no stable Core Data store identity")
    }
    return identity
}

func writerLockURL(storeURL: URL) throws -> URL {
    var storeStatus = stat()
    guard stat(storeURL.path, &storeStatus) == 0,
          storeStatus.st_mode & S_IFMT == S_IFREG else {
        throw HostError.message("selected store is not a regular file")
    }
    let home = ProcessInfo.processInfo.environment["HOME"]
        ?? FileManager.default.homeDirectoryForCurrentUser.path
    let root = URL(fileURLWithPath: home).appendingPathComponent(
        "Library/Application Support/MoneyWiz Tools"
    )
    let directory = root.appendingPathComponent("locks")
    for target in [root, directory] {
        try FileManager.default.createDirectory(
            at: target, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        var status = stat()
        guard lstat(target.path, &status) == 0,
              status.st_mode & S_IFMT == S_IFDIR,
              status.st_uid == getuid(), chmod(target.path, 0o700) == 0 else {
            throw HostError.message("writer lock directory must be private and owned by this user")
        }
    }
    return directory.appendingPathComponent("\(storeStatus.st_dev)-\(storeStatus.st_ino).lock")
}

func withWriterLock<T>(storeURL: URL, body: () throws -> T) throws -> T {
    let lockURL = try writerLockURL(storeURL: storeURL)
    let lockFD = open(lockURL.path, O_RDWR | O_CREAT | O_NOFOLLOW, 0o600)
    guard lockFD >= 0 else { throw HostError.message("cannot open private writer lock") }
    defer { close(lockFD) }
    var lockStatus = stat()
    guard fstat(lockFD, &lockStatus) == 0,
          lockStatus.st_mode & S_IFMT == S_IFREG,
          lockStatus.st_uid == getuid(), fchmod(lockFD, 0o600) == 0 else {
        throw HostError.message("writer lock is not a private regular file")
    }
    if let inherited = ProcessInfo.processInfo.environment["MONEYWIZ_WRITER_LOCK_FD"] {
        var inheritedStatus = stat()
        guard let inheritedFD = Int32(inherited),
              fstat(inheritedFD, &inheritedStatus) == 0,
              inheritedStatus.st_dev == lockStatus.st_dev,
              inheritedStatus.st_ino == lockStatus.st_ino,
              flock(inheritedFD, LOCK_EX | LOCK_NB) == 0 else {
            throw HostError.message("inherited writer lock FD does not identify the selected store lock")
        }
        return try body()
    }
    guard flock(lockFD, LOCK_EX | LOCK_NB) == 0 else {
        throw HostError.message("another cooperating MoneyWiz writer holds the selected store lock")
    }
    defer { _ = flock(lockFD, LOCK_UN) }
    return try body()
}

func run() throws {
    let invocation = Array(CommandLine.arguments.dropFirst())
    if invocation.first == "--model-checksum" {
        guard invocation.count == 2 else {
            throw HostError.message("usage: MoneyWizTools --model-checksum PATH")
        }
        let checksum = try readModelChecksum(at: URL(fileURLWithPath: invocation[1]))
        FileHandle.standardOutput.write(Data((checksum + "\n").utf8))
        return
    }
    guard Bundle.main.bundleIdentifier == expectedBundleIdentifier else {
        throw HostError.message("host must run from the installed MoneyWiz Tools.app bundle")
    }
    let arguments = try parseWriterArguments()
    guard FileManager.default.fileExists(atPath: arguments.store.path) else {
        throw HostError.message("database file not found: \(arguments.store.path)")
    }
    guard FileManager.default.fileExists(atPath: arguments.model.path) else {
        throw HostError.message("managed-object model not found: \(arguments.model.path)")
    }
    let data = try Data(contentsOf: arguments.plan)
    let rawObject = try JSONSerialization.jsonObject(with: data)
    guard let rawPlan = rawObject as? [String: Any],
          let contractVersion = rawPlan["contract_version"] as? Int else {
        throw HostError.message("writer plan must be a versioned JSON object")
    }
    guard !arguments.recoverOnly || contractVersion == 2 else {
        throw HostError.message("inspection-only recovery requires contract version 2")
    }
    try requireMoneyWizStopped()
    configureTransformers()
    let encoded = try withWriterLock(storeURL: arguments.store) {
    switch contractVersion {
    case 1:
        let plan = try JSONDecoder().decode(WriterPlan.self, from: data)
        let expectedChecksum = try validateWriterPlan(plan)
        let container = try loadContainer(
            storeURL: arguments.store, modelURL: arguments.model, expectedChecksum: expectedChecksum
        )
        return try JSONEncoder().encode(try writePlan(plan, container: container))
    case 2:
        let plan = try JSONDecoder().decode(WriterPlanV2.self, from: data)
        try validateWriterPlanV2(plan, rawPlan: rawPlan)
        let appURL = URL(fileURLWithPath: plan.appIdentity.path).standardizedFileURL
        guard let moneyWizApp = Bundle(url: appURL),
              moneyWizApp.bundleIdentifier == plan.appIdentity.bundleID,
              let installedVersion = moneyWizApp.object(
                forInfoDictionaryKey: "CFBundleShortVersionString"
              ) as? String,
              plan.appIdentity.version == installedVersion else {
            throw HostError.message("writer v2 app identity does not match the declared MoneyWiz app")
        }
        let selectedModelPath = arguments.model.standardizedFileURL.path
        guard selectedModelPath.hasPrefix(appURL.path + "/") else {
            throw HostError.message("writer v2 model is not contained by the declared MoneyWiz app")
        }
        let actualStoreIdentity = try storeIdentity(at: arguments.store)
        guard plan.appIdentity.modelPath == selectedModelPath,
              plan.storeIdentity.storeUUID == actualStoreIdentity else {
            throw HostError.message("writer v2 runtime store or model identity does not match reviewed plan")
        }
        if plan.capability.hasPrefix("write.create-") {
            guard moneyWizApp.bundleIdentifier == "com.moneywiz.personalfinance",
                  installedVersion == "2026.37.1",
                  moneyWizApp.object(forInfoDictionaryKey: "CFBundleVersion") as? String == "449" else {
                throw HostError.message("W01 disposable evidence is limited to TestFlight 2026.37.1 build 449")
            }
            let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
                ofType: NSSQLiteStoreType, at: arguments.store, options: nil)
            guard metadata["MoneyWizToolsDisposableFixture"] as? String == "W01-v1" else {
                throw HostError.message("W01 live creation remains blocked; marked disposable fixture required")
            }
        }
        let container = try loadContainer(
            storeURL: arguments.store, modelURL: arguments.model,
            expectedChecksum: plan.modelChecksum, readOnly: arguments.recoverOnly
        )
        return try JSONEncoder().encode(
            try arguments.recoverOnly
                ? recoverPlanV2(plan, container: container)
                : writePlanV2(plan, container: container)
        )
    default:
        throw HostError.message("unsupported Core Data writer contract version")
    }
    }
    FileHandle.standardOutput.write(encoded)
    FileHandle.standardOutput.write(Data([0x0A]))
}

#if !MONEYWIZ_TOOLS_TESTING
    @main
    struct MoneyWizToolsHost {
        static func main() {
            do {
                try run()
            } catch {
                let message = "error: \(error.localizedDescription)\n"
                FileHandle.standardError.write(Data(message.utf8))
                exit(2)
            }
        }
    }
#endif
