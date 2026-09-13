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
    let targetPayeeGID: String
    let ownerURI: String
    let sourceEventID: String
    let expectedPostcondition: PayeePostcondition
    let allowedChangedFields: [String]

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
    }
}

struct PayeePostcondition: Decodable {
    let payeeGID: String

    enum CodingKeys: String, CodingKey { case payeeGID = "payee_gid" }
}

struct WriterOperationResultV2: Encodable {
    let operationID: String
    let status: String
    let transactionEntity: String
    let transactionGID: String
    let durableURI: String
    let durableNumericID: String
    let oldPayeeGID: String?
    let newPayeeGID: String?

    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id"
        case status
        case transactionEntity = "transaction_entity"
        case transactionGID = "transaction_gid"
        case durableURI = "durable_uri"
        case durableNumericID = "durable_numeric_id"
        case oldPayeeGID = "old_payee_gid"
        case newPayeeGID = "new_payee_gid"
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
          plan.capability == policy.capability,
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
    for operation in plan.operations {
        guard operation.kind == "reassign_payee",
              operation.capability == policy.capability,
              policy.transactionEntities.contains(operation.transactionEntity),
              !isBlank(operation.operationID),
              !isBlank(operation.transactionGID),
              !isBlank(operation.targetPayeeGID),
              !isBlank(operation.ownerURI),
              !isBlank(operation.sourceEventID),
              operation.sourceEventID == plan.sourceEventID,
              operation.expectedPostcondition.payeeGID == operation.targetPayeeGID,
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
    let target = try fetchExactObject(entityName: "Payee", gid: operation.targetPayeeGID, context: context)
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
            var recovered: [(WriterOperationV2, NSManagedObject, String?)] = []
            for operation in plan.operations {
                let (transaction, _) = try resolveV2References(operation, plan: plan, context: context)
                recovered.append((operation, transaction, payeeGID(transaction)))
            }
            let classification = classifyRecoveryStates(recovered.map {
                (expectedOld: $0.0.expectedOldPayeeGID, target: $0.0.targetPayeeGID, actual: $0.2)
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
                        newPayeeGID: actual
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
            var resolved: [(WriterOperationV2, NSManagedObject, NSManagedObject, String?, [String: NSObject])] = []
            for operation in plan.operations {
                let (transaction, target) = try resolveV2References(operation, plan: plan, context: context)
                let oldPayee = payeeGID(transaction)
                resolved.append((operation, transaction, target, oldPayee, try immutableTransactionFingerprint(transaction)))
            }
            let recoveryClassification = classifyRecoveryStates(resolved.map {
                (expectedOld: $0.0.expectedOldPayeeGID, target: $0.0.targetPayeeGID, actual: $0.3)
            })
            if recoveryClassification == "noop" {
                let noops = resolved.map { operation, transaction, _, oldPayee, _ in
                    WriterOperationResultV2(
                        operationID: operation.operationID, status: "noop",
                        transactionEntity: operation.transactionEntity, transactionGID: operation.transactionGID,
                        durableURI: transaction.objectID.uriRepresentation().absoluteString,
                        durableNumericID: durableNumericID(transaction.objectID), oldPayeeGID: oldPayee,
                        newPayeeGID: oldPayee
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
                        guard actualPayee == operation.expectedPostcondition.payeeGID else {
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
                            newPayeeGID: actualPayee
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
