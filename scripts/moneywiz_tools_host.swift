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
    let sourceScope: ReconcileSourceScope?
    let destinationAccount: TransferDestinationAccount?
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
        case sourceScope = "source_scope"
        case destinationAccount = "destination_account"
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

struct ReconcileSourceScope: Decodable {
    let scope: String
    let readStatus: String
    let externalSourceVerified: Bool
    let accountGID: String
    let currencyUnit: String
    let verifiedBalance: String
    let sourceCount: Int
    let parsedCount: Int
    let transactionGIDs: [String]

    enum CodingKeys: String, CodingKey {
        case scope, accountGID = "account_gid", currencyUnit = "currency_unit"
        case readStatus = "read_status", externalSourceVerified = "external_source_verified"
        case verifiedBalance = "verified_balance", sourceCount = "source_count"
        case parsedCount = "parsed_count", transactionGIDs = "transaction_gids"
    }
}

struct TransferDestinationAccount: Decodable {
    let accountGID: String
    let currencyUnit: String
    let expectedCachedBalance: String
    enum CodingKeys: String, CodingKey {
        case accountGID = "account_gid", currencyUnit = "currency_unit"
        case expectedCachedBalance = "expected_cached_balance"
    }
}

struct TransferOldRow: Decodable {
    let transactionEntity: String
    let transactionGID: String
    let transactionNumericID: String
    let accountGID: String
    let amount: String
    let currencyUnit: String
    let occurredAt: String
    let status: Int
    let flags: Int
    let reconciled: Bool
    let note: String?
    let description: String?
    let payeeGID: String?
    let tagGIDs: [String]
    let categoryAssignmentURIs: [String]
    enum CodingKeys: String, CodingKey {
        case transactionEntity = "transaction_entity", transactionGID = "transaction_gid"
        case transactionNumericID = "transaction_numeric_id", accountGID = "account_gid"
        case amount, currencyUnit = "currency_unit", occurredAt = "occurred_at"
        case status, flags, reconciled, note, description, payeeGID = "payee_gid"
        case tagGIDs = "tag_gids", categoryAssignmentURIs = "category_assignment_uris"
    }
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
    let changes: [String: EditScalar]?
    let expectedPrior: [String: EditScalar]?
    let correctionMode: String?
    let target: AssignmentState?
    let expectedAssignments: AssignmentState?
    let replacementMode: String?
    let expectedReconciled: Bool?
    let targetReconciled: Bool?
    let expectedNativeStatus: Int?
    let expectedNativeFlags: Int?
    let correctionReason: String?
    let balanceUnit: String?
    let expectedPriorBalance: String?
    let targetBalance: String?
    let transactionNumericID: String?
    let expectedAmount: String?
    let expectedReconcileAmount: String?
    let deletionReason: String?
    let recipientTransactionGID: String?
    let sourceOld: TransferOldRow?
    let destinationOld: TransferOldRow?
    let sendAt: String?
    let receiveAt: String?
    let senderAmount: String?
    let recipientAmount: String?
    let exchangeRate: String?
    let feeAmount: String?
    let accountMode: String?
    let cashEventType: String?
    let investmentSymbol: String?
    let holdingGID: String?
    let holdingSymbol: String?
    let assetType: Int?
    let quantity: String?
    let unitPrice: String?
    let fee: String?
    let feeCurrency: String?
    let expectedPriorCash: String?
    let expectedFinalCash: String?
    let expectedPriorUnits: String?
    let expectedFinalUnits: String?

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
        case changes
        case expectedPrior = "expected_prior"
        case correctionMode = "correction_mode"
        case target
        case expectedAssignments = "expected_assignments"
        case replacementMode = "replacement_mode"
        case expectedReconciled = "expected_reconciled"
        case targetReconciled = "target_reconciled"
        case expectedNativeStatus = "expected_native_status"
        case expectedNativeFlags = "expected_native_flags"
        case correctionReason = "correction_reason"
        case balanceUnit = "balance_unit"
        case expectedPriorBalance = "expected_prior_balance"
        case targetBalance = "target_balance"
        case transactionNumericID = "transaction_numeric_id"
        case expectedAmount = "expected_amount"
        case expectedReconcileAmount = "expected_reconcile_amount"
        case deletionReason = "deletion_reason"
        case recipientTransactionGID = "recipient_transaction_gid"
        case sourceOld = "source_old"
        case destinationOld = "destination_old"
        case sendAt = "send_at", receiveAt = "receive_at"
        case senderAmount = "sender_amount", recipientAmount = "recipient_amount"
        case exchangeRate = "exchange_rate", feeAmount = "fee_amount"
        case accountMode = "account_mode", cashEventType = "cash_event_type"
        case investmentSymbol = "investment_symbol"
        case holdingGID = "holding_gid", holdingSymbol = "holding_symbol"
        case assetType = "asset_type", quantity, unitPrice = "unit_price", fee
        case feeCurrency = "fee_currency", expectedPriorCash = "expected_prior_cash"
        case expectedFinalCash = "expected_final_cash", expectedPriorUnits = "expected_prior_units"
        case expectedFinalUnits = "expected_final_units"
    }
}

enum EditScalar: Codable, Equatable {
    case text(String)
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null } else { self = .text(try c.decode(String.self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self { case .null: try c.encodeNil(); case .text(let s): try c.encode(s) }
    }
    var string: String? { if case .text(let s) = self { return s }; return nil }
}

struct EditPostcondition: Codable {
    let fields: [String: EditScalar]
    let expectedBalanceDelta: String
    enum CodingKeys: String, CodingKey { case fields; case expectedBalanceDelta = "expected_balance_delta" }
}

struct CategorySplit: Codable, Equatable {
    let categoryGID: String
    let amount: String

    enum CodingKeys: String, CodingKey { case categoryGID = "category_gid"; case amount }
}

struct AssignmentState: Codable, Equatable {
    let payeeGID: String?
    let categorySplits: [CategorySplit]
    enum CodingKeys: String, CodingKey {
        case payeeGID = "payee_gid", categorySplits = "category_splits"
    }
}

struct AssignmentPostcondition: Encodable {
    let payeeGID: String?
    let categorySplits: [CategorySplit]
    let expectedBalanceDelta: String
    enum CodingKeys: String, CodingKey {
        case payeeGID = "payee_gid", categorySplits = "category_splits"
        case expectedBalanceDelta = "expected_balance_delta"
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(payeeGID, forKey: .payeeGID)
        try c.encode(categorySplits, forKey: .categorySplits)
        try c.encode(expectedBalanceDelta, forKey: .expectedBalanceDelta)
    }
}

struct ReconcilePostcondition: Encodable {
    let reconciled: Bool
    let nativeStatus: Int
    let nativeFlags: Int
    let expectedBalanceDelta: String
    enum CodingKeys: String, CodingKey {
        case reconciled, nativeStatus = "native_status", nativeFlags = "native_flags"
        case expectedBalanceDelta = "expected_balance_delta"
    }
}

struct AdjustBalancePostcondition: Encodable {
    let transactionEntity: String
    let transactionGID: String
    let accountGID: String
    let ownerURI: String
    let balanceUnit: String
    let expectedPriorBalance: String
    let targetBalance: String
    let expectedBalanceDelta: String
    let currencyUnit: String
    let occurredAt: String
    let timezone: String
    enum CodingKeys: String, CodingKey {
        case transactionEntity = "transaction_entity", transactionGID = "transaction_gid"
        case accountGID = "account_gid", ownerURI = "owner_uri", balanceUnit = "balance_unit"
        case expectedPriorBalance = "expected_prior_balance", targetBalance = "target_balance"
        case expectedBalanceDelta = "expected_balance_delta", currencyUnit = "currency_unit"
        case occurredAt = "occurred_at", timezone
    }
}

struct DeleteAdjustmentPostcondition: Encodable {
    let transactionAbsent = true
    let transactionGID: String
    let accountGID: String
    let targetBalance: String
    enum CodingKeys: String, CodingKey {
        case transactionAbsent = "transaction_absent", transactionGID = "transaction_gid"
        case accountGID = "account_gid", targetBalance = "target_balance"
    }
}

struct TransferPostcondition: Encodable {
    let oldSenderGID: String
    let oldSenderNumericID: String
    let oldRecipientGID: String?
    let oldRecipientNumericID: String?
    let senderGID: String
    let recipientGID: String
    let senderAccountGID: String
    let recipientAccountGID: String
    let senderAmount: String
    let recipientAmount: String
    let sendAt: String
    let receiveAt: String
    let exchangeRate: String
    let feeAmount: String
    let senderBalance: String
    let recipientBalance: String
    enum CodingKeys: String, CodingKey {
        case oldSenderGID = "old_sender_gid", oldSenderNumericID = "old_sender_numeric_id"
        case oldRecipientGID = "old_recipient_gid", oldRecipientNumericID = "old_recipient_numeric_id"
        case senderGID = "sender_gid", recipientGID = "recipient_gid"
        case senderAccountGID = "sender_account_gid", recipientAccountGID = "recipient_account_gid"
        case senderAmount = "sender_amount", recipientAmount = "recipient_amount"
        case sendAt = "send_at", receiveAt = "receive_at"
        case exchangeRate = "exchange_rate", feeAmount = "fee_amount"
        case senderBalance = "sender_balance", recipientBalance = "recipient_balance"
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(oldSenderGID, forKey: .oldSenderGID)
        try c.encode(oldSenderNumericID, forKey: .oldSenderNumericID)
        try c.encode(oldRecipientGID, forKey: .oldRecipientGID)
        try c.encode(oldRecipientNumericID, forKey: .oldRecipientNumericID)
        try c.encode(senderGID, forKey: .senderGID)
        try c.encode(recipientGID, forKey: .recipientGID)
        try c.encode(senderAccountGID, forKey: .senderAccountGID)
        try c.encode(recipientAccountGID, forKey: .recipientAccountGID)
        try c.encode(senderAmount, forKey: .senderAmount)
        try c.encode(recipientAmount, forKey: .recipientAmount)
        try c.encode(sendAt, forKey: .sendAt)
        try c.encode(receiveAt, forKey: .receiveAt)
        try c.encode(exchangeRate, forKey: .exchangeRate)
        try c.encode(feeAmount, forKey: .feeAmount)
        try c.encode(senderBalance, forKey: .senderBalance)
        try c.encode(recipientBalance, forKey: .recipientBalance)
    }
}

struct TransferDetails: Encodable {
    let recipientGID: String
    let recipientNumericID: String
    let recipientURI: String
    let oldSenderNumericID: String
    let oldRecipientNumericID: String?
    let reciprocalLinksVerified = true
    enum CodingKeys: String, CodingKey {
        case recipientGID = "recipient_gid", recipientNumericID = "recipient_numeric_id"
        case recipientURI = "recipient_uri", oldSenderNumericID = "old_sender_numeric_id"
        case oldRecipientNumericID = "old_recipient_numeric_id"
        case reciprocalLinksVerified = "reciprocal_links_verified"
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(recipientGID, forKey: .recipientGID)
        try c.encode(recipientNumericID, forKey: .recipientNumericID)
        try c.encode(recipientURI, forKey: .recipientURI)
        try c.encode(oldSenderNumericID, forKey: .oldSenderNumericID)
        try c.encode(oldRecipientNumericID, forKey: .oldRecipientNumericID)
        try c.encode(reciprocalLinksVerified, forKey: .reciprocalLinksVerified)
    }
}

struct InvestmentDetails: Encodable {
    let accountMode: String
    let cashEventType: String?
    let investmentSymbol: String?
    let holdingGID: String?
    let holdingSymbol: String?
    let assetType: Int?
    let quantity: String
    let unitPrice: String
    let fee: String
    let feeCurrency: String
    let expectedPriorCash: String
    let expectedFinalCash: String
    let expectedPriorUnits: String?
    let expectedFinalUnits: String?

    enum CodingKeys: String, CodingKey {
        case accountMode = "account_mode", cashEventType = "cash_event_type"
        case investmentSymbol = "investment_symbol"
        case holdingGID = "holding_gid", holdingSymbol = "holding_symbol"
        case assetType = "asset_type", quantity, unitPrice = "unit_price", fee
        case feeCurrency = "fee_currency", expectedPriorCash = "expected_prior_cash"
        case expectedFinalCash = "expected_final_cash", expectedPriorUnits = "expected_prior_units"
        case expectedFinalUnits = "expected_final_units"
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(accountMode, forKey: .accountMode)
        try c.encode(cashEventType, forKey: .cashEventType)
        try c.encode(investmentSymbol, forKey: .investmentSymbol)
        try c.encode(holdingGID, forKey: .holdingGID)
        try c.encode(holdingSymbol, forKey: .holdingSymbol)
        try c.encode(assetType, forKey: .assetType)
        try c.encode(quantity, forKey: .quantity)
        try c.encode(unitPrice, forKey: .unitPrice)
        try c.encode(fee, forKey: .fee)
        try c.encode(feeCurrency, forKey: .feeCurrency)
        try c.encode(expectedPriorCash, forKey: .expectedPriorCash)
        try c.encode(expectedFinalCash, forKey: .expectedFinalCash)
        try c.encode(expectedPriorUnits, forKey: .expectedPriorUnits)
        try c.encode(expectedFinalUnits, forKey: .expectedFinalUnits)
    }
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
    var editPostcondition: EditPostcondition? = nil
    var assignmentPostcondition: AssignmentPostcondition? = nil
    var reconcilePostcondition: ReconcilePostcondition? = nil
    var adjustBalancePostcondition: AdjustBalancePostcondition? = nil
    var deleteAdjustmentPostcondition: DeleteAdjustmentPostcondition? = nil
    var transferPostcondition: TransferPostcondition? = nil
    var transferDetails: TransferDetails? = nil
    var investmentDetails: InvestmentDetails? = nil

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
        case transferDetails = "transfer_details"
        case investmentDetails = "investment_details"
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
        try container.encodeIfPresent(transferDetails, forKey: .transferDetails)
        try container.encodeIfPresent(investmentDetails, forKey: .investmentDetails)
        if let transferPostcondition { try container.encode(transferPostcondition, forKey: .postcondition) }
        else if let deleteAdjustmentPostcondition { try container.encode(deleteAdjustmentPostcondition, forKey: .postcondition) }
        else if let adjustBalancePostcondition { try container.encode(adjustBalancePostcondition, forKey: .postcondition) }
        else if let reconcilePostcondition { try container.encode(reconcilePostcondition, forKey: .postcondition) }
        else if let assignmentPostcondition { try container.encode(assignmentPostcondition, forKey: .postcondition) }
        else if let editPostcondition { try container.encode(editPostcondition, forKey: .postcondition) }
        else { try container.encodeIfPresent(postcondition, forKey: .postcondition) }
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
    var requiredKeys: Set<String> = [
        "contract_version", "operation_schema_version", "plan_id", "plan_digest", "profile_id",
        "model_checksum", "store_identity", "owner_uri", "app_identity", "capability", "created_at",
        "timezone", "source_interval", "source_evidence_refs", "expected_account_gid",
        "expected_cached_account_balance", "currency_unit", "source_event_id", "operations",
    ]
    let w04 = ["write.reconcile", "write.unreconcile"].contains(plan.capability)
    if w04 { requiredKeys.insert("source_scope") }
    let w07 = plan.capability == "write.replace-import-with-transfer"
    if w07 { requiredKeys.insert("destination_account") }
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
        if kind == "edit_transaction" {
            try validateEditOperationShape(rawOperation, plan: plan)
            continue
        }
        if kind == "assign_payee_categories" {
            try validateAssignmentOperationShape(rawOperation, plan: plan)
            continue
        }
        if kind == "reconcile_transaction" || kind == "unreconcile_transaction" {
            try validateReconcileOperationShape(rawOperation, plan: plan)
            continue
        }
        if kind == "adjust_investment_total" {
            try validateAdjustBalanceShape(rawOperation, plan: plan)
            continue
        }
        if kind == "delete_investment_total_adjustment" {
            try validateDeleteAdjustmentShape(rawOperation, plan: plan)
            continue
        }
        if kind == "replace_import_with_transfer" {
            try validateTransferShape(rawOperation, plan: plan)
            continue
        }
        if kind == "create_income" || kind == "create_expense" || kind == "create_refund" ||
           ["investment_income", "investment_expense", "investment_buy", "investment_sell"].contains(kind) {
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
          (plan.capability == policy.capability || ["write.create-income", "write.create-expense", "write.create-refund", "write.edit-transaction", "write.assign-payee-categories", "write.reconcile", "write.unreconcile", "write.adjust-balance-investment-total", "write.delete-adjust-balance-investment-total", "write.replace-import-with-transfer", "write.investment-income", "write.investment-expense", "write.investment-buy", "write.investment-sell"].contains(plan.capability)),
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
    if w04 { try validateReconcileSourceScope(plan.sourceScope, raw: rawPlan["source_scope"], plan: plan) }
    if w07 {
        guard let destination = plan.destinationAccount,
              let rawDestination = rawPlan["destination_account"] as? [String: Any],
              Set(rawDestination.keys) == ["account_gid", "currency_unit", "expected_cached_balance"],
              !isBlank(destination.accountGID), destination.accountGID != plan.expectedAccountGID,
              destination.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
              plan.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil else {
            throw HostError.message("W07 destination account guard is invalid")
        }
        _ = try decimalValue(destination.expectedCachedBalance, field: "W07 destination balance")
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
    if plan.operations.contains(where: { $0.kind == "edit_transaction" }) &&
       !plan.operations.allSatisfy({ $0.kind == "edit_transaction" }) {
        throw HostError.message("W02 plans must contain homogeneous edit operations")
    }
    if plan.operations.contains(where: { $0.kind == "assign_payee_categories" }) &&
       !plan.operations.allSatisfy({ $0.kind == "assign_payee_categories" }) {
        throw HostError.message("W03 plans must contain homogeneous assignment operations")
    }
    if w04 && !plan.operations.allSatisfy({ $0.capability == plan.capability &&
        $0.kind == (plan.capability == "write.reconcile" ? "reconcile_transaction" : "unreconcile_transaction") }) {
        throw HostError.message("W04 plans must contain homogeneous flag transitions")
    }
    if plan.capability == "write.adjust-balance-investment-total" &&
       (plan.operations.count != 1 || plan.operations[0].kind != "adjust_investment_total") {
        throw HostError.message("W05 requires exactly one investment-total operation")
    }
    if plan.capability == "write.delete-adjust-balance-investment-total" &&
       (plan.operations.count != 1 || plan.operations[0].kind != "delete_investment_total_adjustment") {
        throw HostError.message("W06 requires exactly one investment-total deletion")
    }
    if w07 && (plan.operations.count != 1 || plan.operations[0].kind != "replace_import_with_transfer") {
        throw HostError.message("W07 requires exactly one atomic transfer replacement")
    }
    if ["write.investment-income", "write.investment-expense", "write.investment-buy", "write.investment-sell"].contains(plan.capability) &&
       (plan.operations.count != 1 || !plan.operations[0].kind.hasPrefix("investment_")) {
        throw HostError.message("W08 requires exactly one investment operation")
    }
    for operation in plan.operations {
        if operation.kind == "edit_transaction" || operation.kind == "assign_payee_categories" ||
           operation.kind == "reconcile_transaction" || operation.kind == "unreconcile_transaction" {
            guard operationIDs.insert(operation.operationID).inserted,
                  transactionGIDs.insert(operation.transactionGID).inserted else {
                throw HostError.message("writer v2 operation identifiers and transaction GIDs must be unique")
            }
            continue
        }
        if ["create_income", "create_expense", "create_refund", "adjust_investment_total",
            "investment_income", "investment_expense", "investment_buy", "investment_sell"].contains(operation.kind) {
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
        if operation.kind == "delete_investment_total_adjustment" {
            guard operation.capability == plan.capability,
                  operation.accountGID == plan.expectedAccountGID,
                  operation.currencyUnit == plan.currencyUnit,
                  operation.timezone == plan.timezone,
                  operation.ownerURI == plan.ownerURI,
                  operation.sourceEventID == plan.sourceEventID,
                  operationIDs.insert(operation.operationID).inserted,
                  transactionGIDs.insert(operation.transactionGID).inserted else {
                throw HostError.message("W06 deletion operation differs from its envelope")
            }
            continue
        }
        if operation.kind == "replace_import_with_transfer" {
            guard operation.capability == plan.capability,
                  operation.ownerURI == plan.ownerURI,
                  operation.sourceEventID == plan.sourceEventID,
                  operationIDs.insert(operation.operationID).inserted,
                  transactionGIDs.insert(operation.transactionGID).inserted,
                  let recipientGID = operation.recipientTransactionGID,
                  transactionGIDs.insert(recipientGID).inserted else {
                throw HostError.message("W07 operation identity differs from its envelope")
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

func validateAdjustBalanceShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let fields: Set<String> = ["transaction_entity", "transaction_gid", "account_gid", "owner_uri",
        "balance_unit", "expected_prior_balance", "target_balance", "expected_balance_delta",
        "currency_unit", "occurred_at", "timezone"]
    let required = fields.union(["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"])
    guard Set(raw.keys) == required,
          let post = raw["expected_postcondition"] as? [String: String],
          Set(post.keys) == fields,
          fields.allSatisfy({ post[$0] == raw[$0] as? String }),
          raw["kind"] as? String == "adjust_investment_total",
          raw["capability"] as? String == "write.adjust-balance-investment-total",
          plan.capability == "write.adjust-balance-investment-total",
          raw["transaction_entity"] as? String == "ReconcileTransaction",
          raw["transaction_gid"] as? String == deterministicCreationGID(plan: plan),
          raw["account_gid"] as? String == plan.expectedAccountGID,
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["balance_unit"] as? String == "investment_total",
          raw["currency_unit"] as? String == plan.currencyUnit,
          raw["timezone"] as? String == plan.timezone,
          plan.expectedCachedAccountBalance == "0",
          plan.currencyUnit == "GBP",
          let prior = raw["expected_prior_balance"] as? String,
          let target = raw["target_balance"] as? String,
          let delta = raw["expected_balance_delta"] as? String,
          let occurred = raw["occurred_at"] as? String,
          let operationID = raw["operation_id"] as? String,
          !isBlank(operationID),
          !occurred.contains("."), !plan.createdAt.contains(".") else {
        throw HostError.message("W05 operation shape or envelope is invalid")
    }
    let amounts = try [prior, target, delta].map { try decimalValue($0, field: "W05 amount") }
    guard amounts.allSatisfy({ value in
        var source = value
        var rounded = Decimal()
        NSDecimalRound(&rounded, &source, 2, .plain)
        return rounded == value
    }), amounts[1] - amounts[0] == amounts[2] else {
        throw HostError.message("W05 target minus prior differs from delta")
    }
    let instant = try planTimestamp(occurred)
    let offset = occurred.hasSuffix("Z") ? 0 : {
        let suffix = occurred.suffix(6)
        let seconds = (Int(suffix.dropFirst().prefix(2))! * 60 + Int(suffix.suffix(2))!) * 60
        return seconds * (suffix.first == "-" ? -1 : 1)
    }()
    guard TimeZone(identifier: plan.timezone)?.secondsFromGMT(for: instant) == offset else {
        throw HostError.message("W05 date offset differs from the reviewed timezone")
    }
}

func validateDeleteAdjustmentShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = ["operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "transaction_numeric_id", "account_gid", "owner_uri", "source_event_id",
        "balance_unit", "expected_amount", "expected_reconcile_amount", "expected_prior_balance",
        "target_balance", "expected_balance_delta", "currency_unit", "occurred_at", "timezone",
        "deletion_reason", "expected_postcondition"]
    guard Set(raw.keys) == required,
          raw["kind"] as? String == "delete_investment_total_adjustment",
          raw["capability"] as? String == "write.delete-adjust-balance-investment-total",
          plan.capability == "write.delete-adjust-balance-investment-total",
          raw["transaction_entity"] as? String == "ReconcileTransaction",
          let gid = raw["transaction_gid"] as? String, !isBlank(gid),
          let numericID = raw["transaction_numeric_id"] as? String,
          !numericID.isEmpty, numericID.allSatisfy({ $0.isASCII && $0.isNumber }),
          Int(numericID).map({ $0 > 0 }) == true,
          Int(numericID).map(String.init) == numericID,
          raw["account_gid"] as? String == plan.expectedAccountGID,
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["balance_unit"] as? String == "investment_total",
          raw["currency_unit"] as? String == plan.currencyUnit,
          raw["timezone"] as? String == plan.timezone,
          plan.expectedCachedAccountBalance == "0", plan.currencyUnit == "GBP",
          let reason = raw["deletion_reason"] as? String, !isBlank(reason),
          let prior = raw["expected_prior_balance"] as? String,
          let target = raw["target_balance"] as? String,
          let amount = raw["expected_amount"] as? String,
          let reconcile = raw["expected_reconcile_amount"] as? String,
          let delta = raw["expected_balance_delta"] as? String,
          let occurred = raw["occurred_at"] as? String,
          let post = raw["expected_postcondition"] as? [String: Any],
          Set(post.keys) == ["transaction_absent", "transaction_gid", "account_gid", "target_balance"],
          post["transaction_absent"] as? Bool == true,
          post["transaction_gid"] as? String == gid,
          post["account_gid"] as? String == plan.expectedAccountGID,
          post["target_balance"] as? String == target else {
        throw HostError.message("W06 operation shape or envelope is invalid")
    }
    let values = try [amount, reconcile, prior, target, delta].map {
        try decimalValue($0, field: "W06 amount")
    }
    guard values[0] != 0, values[1] == values[2], values[3] == values[2] - values[0],
          values[4] == -values[0], values.allSatisfy({ value in
              var source = value
              var rounded = Decimal()
              NSDecimalRound(&rounded, &source, 2, .plain)
              return rounded == value
          }) else {
        throw HostError.message("W06 deletion balances differ from the reviewed target")
    }
    let instant = try planTimestamp(occurred)
    let offset = occurred.hasSuffix("Z") ? 0 : {
        let suffix = occurred.suffix(6)
        let seconds = (Int(suffix.dropFirst().prefix(2))! * 60 + Int(suffix.suffix(2))!) * 60
        return seconds * (suffix.first == "-" ? -1 : 1)
    }()
    guard TimeZone(identifier: plan.timezone)?.secondsFromGMT(for: instant) == offset else {
        throw HostError.message("W06 date offset differs from the reviewed timezone")
    }
}

func deterministicTransferGID(plan: WriterPlanV2, suffix: String) throws -> String {
    let identity = [
        "owner_uri": plan.ownerURI,
        "source_event_id": plan.sourceEventID + suffix,
        "store_uuid": plan.storeIdentity.storeUUID,
    ]
    let data = try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys, .withoutEscapingSlashes])
    let bytes = Array(SHA256.hash(data: data).prefix(16))
    let hex = bytes.map { String(format: "%02X", $0) }.joined()
    return "\(hex.prefix(8))-\(hex.dropFirst(8).prefix(4))-\(hex.dropFirst(12).prefix(4))-\(hex.dropFirst(16).prefix(4))-\(hex.dropFirst(20))"
}

func validateTransferOldRowShape(_ value: Any, entity: String, accountGID: String,
                                 currency: String) throws -> [String: Any] {
    let required: Set<String> = ["transaction_entity", "transaction_gid", "transaction_numeric_id",
        "account_gid", "amount", "currency_unit", "occurred_at", "status", "flags",
        "reconciled", "note", "description", "payee_gid", "tag_gids",
        "category_assignment_uris"]
    guard let row = value as? [String: Any], Set(row.keys) == required,
          row["transaction_entity"] as? String == entity,
          row["account_gid"] as? String == accountGID,
          row["currency_unit"] as? String == currency,
          let gid = row["transaction_gid"] as? String, !isBlank(gid),
          let numericID = row["transaction_numeric_id"] as? String,
          let parsedID = Int(numericID), parsedID > 0, String(parsedID) == numericID,
          let amount = row["amount"] as? String,
          let occurred = row["occurred_at"] as? String,
          let status = row["status"] as? Int, status == 2,
          let flags = row["flags"] as? Int, flags >= 0,
          row["reconciled"] is Bool,
          row["note"] is String || row["note"] is NSNull,
          row["description"] is String || row["description"] is NSNull,
          row["payee_gid"] is String || row["payee_gid"] is NSNull,
          let tags = row["tag_gids"] as? [String], tags == Array(Set(tags)).sorted(),
          let categories = row["category_assignment_uris"] as? [String],
          categories == Array(Set(categories)).sorted(),
          tags.allSatisfy({ !isBlank($0) }), categories.allSatisfy({ !isBlank($0) }) else {
        throw HostError.message("W07 imported row shape or identity is invalid")
    }
    let parsedAmount = try decimalValue(amount, field: "W07 imported amount")
    guard NSDecimalNumber(decimal: parsedAmount).stringValue == amount else {
        throw HostError.message("W07 imported amount must be canonical")
    }
    _ = try precisePlanTimestamp(occurred)
    return row
}

func validateTransferShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = ["operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "recipient_transaction_gid", "owner_uri", "source_event_id",
        "source_old", "destination_old", "send_at", "receive_at", "sender_amount",
        "recipient_amount", "exchange_rate", "fee_amount", "expected_postcondition"]
    guard Set(raw.keys) == required,
          raw["kind"] as? String == "replace_import_with_transfer",
          raw["capability"] as? String == "write.replace-import-with-transfer",
          plan.capability == "write.replace-import-with-transfer",
          raw["transaction_entity"] as? String == "TransferWithdrawTransaction",
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["transaction_gid"] as? String == (try deterministicTransferGID(plan: plan, suffix: ":withdraw")),
          raw["recipient_transaction_gid"] as? String == (try deterministicTransferGID(plan: plan, suffix: ":deposit")),
          let destination = plan.destinationAccount,
          let oldSource = raw["source_old"],
          let sendAt = raw["send_at"] as? String,
          let receiveAt = raw["receive_at"] as? String,
          let senderText = raw["sender_amount"] as? String,
          let recipientText = raw["recipient_amount"] as? String,
          let rateText = raw["exchange_rate"] as? String,
          let feeText = raw["fee_amount"] as? String,
          let post = raw["expected_postcondition"] as? [String: Any] else {
        throw HostError.message("W07 operation shape differs from the reviewed plan")
    }
    let source = try validateTransferOldRowShape(oldSource, entity: "WithdrawTransaction",
        accountGID: plan.expectedAccountGID, currency: plan.currencyUnit)
    let oldDestination = raw["destination_old"] is NSNull ? nil : raw["destination_old"]
    let recipient = try oldDestination.map {
        try validateTransferOldRowShape($0, entity: "DepositTransaction",
            accountGID: destination.accountGID, currency: destination.currencyUnit)
    }
    if let recipient {
        guard source["transaction_gid"] as? String != recipient["transaction_gid"] as? String,
              source["transaction_numeric_id"] as? String != recipient["transaction_numeric_id"] as? String else {
            throw HostError.message("W07 old row identities overlap")
        }
    }
    let sender = try decimalValue(senderText, field: "W07 sender")
    let received = try decimalValue(recipientText, field: "W07 recipient")
    let rate = try decimalValue(rateText, field: "W07 rate")
    let fee = try decimalValue(feeText, field: "W07 fee")
    guard sender < 0, received > 0, rate > 0, fee == 0,
          try decimalValue(source["amount"] as! String, field: "W07 old sender") == sender,
          try recipient.map({ try decimalValue($0["amount"] as! String, field: "W07 old recipient") == received }) ?? true,
          abs((-sender * rate) - received) <= Decimal(string: "0.01")!,
          [senderText, recipientText, rateText, feeText].enumerated().allSatisfy({ index, text in
              NSDecimalNumber(decimal: [sender, received, rate, fee][index]).stringValue == text
          }) else {
        throw HostError.message("W07 amount, directional rate or zero-fee equation is invalid")
    }
    _ = try precisePlanTimestamp(sendAt)
    _ = try precisePlanTimestamp(receiveAt)
    let prior = try decimalValue(destination.expectedCachedBalance, field: "W07 destination balance")
    let resulting = prior + (recipient == nil ? received : 0)
    let senderBalance = try decimalValue(plan.expectedCachedAccountBalance, field: "W07 source balance")
    let expected: [String: Any] = [
        "old_sender_gid": source["transaction_gid"]!,
        "old_sender_numeric_id": source["transaction_numeric_id"]!,
        "old_recipient_gid": recipient?["transaction_gid"] ?? NSNull(),
        "old_recipient_numeric_id": recipient?["transaction_numeric_id"] ?? NSNull(),
        "sender_gid": raw["transaction_gid"]!,
        "recipient_gid": raw["recipient_transaction_gid"]!,
        "sender_account_gid": plan.expectedAccountGID,
        "recipient_account_gid": destination.accountGID,
        "sender_amount": senderText, "recipient_amount": recipientText,
        "send_at": sendAt, "receive_at": receiveAt,
        "exchange_rate": rateText, "fee_amount": feeText,
        "sender_balance": NSDecimalNumber(decimal: senderBalance).stringValue,
        "recipient_balance": NSDecimalNumber(decimal: resulting).stringValue,
    ]
    guard NSDictionary(dictionary: post).isEqual(to: expected) else {
        throw HostError.message("W07 postcondition differs from reviewed transfer")
    }
}

func validateCreationOperationShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let investmentKinds: Set<String> = ["investment_income", "investment_expense", "investment_buy", "investment_sell"]
    let investment = investmentKinds.contains(raw["kind"] as? String ?? "")
    let extra: Set<String> = ["account_mode", "cash_event_type", "investment_symbol", "holding_gid", "holding_symbol",
        "asset_type", "quantity", "unit_price", "fee", "fee_currency",
        "expected_prior_cash", "expected_final_cash", "expected_prior_units", "expected_final_units"]
    let base: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "account_gid", "owner_uri", "source_event_id", "amount", "currency_unit",
        "occurred_at", "timezone", "payee_gid", "category_splits", "tag_gids", "note",
        "refund_reference", "expected_balance_delta", "expected_postcondition",
    ]
    let required = investment ? base.union(extra) : base
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
          Set(postcondition.keys) == base.subtracting(["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"]),
          postcondition["transaction_entity"] as? String == entity,
          postcondition["transaction_gid"] as? String == raw["transaction_gid"] as? String,
          postcondition["amount"] as? String == amount,
          postcondition["expected_balance_delta"] as? String == delta else {
        throw HostError.message("writer v2 creation operation contains unknown, missing, or unreviewed fields")
    }
    let expectedPost = raw.filter { !["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"].contains($0.key) && !extra.contains($0.key) }
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
        "investment_income": ("write.investment-income", "DepositTransaction", 1),
        "investment_expense": ("write.investment-expense", "WithdrawTransaction", -1),
        "investment_buy": ("write.investment-buy", "InvestmentBuyTransaction", -1),
        "investment_sell": ("write.investment-sell", "InvestmentSellTransaction", 1),
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
    if investment {
        let operation = plan.operations[0]
        guard raw["transaction_gid"] as? String == deterministicCreationGID(plan: plan),
              raw["account_gid"] as? String == plan.expectedAccountGID,
              raw["owner_uri"] as? String == plan.ownerURI,
              raw["source_event_id"] as? String == plan.sourceEventID,
              raw["currency_unit"] as? String == plan.currencyUnit,
              raw["timezone"] as? String == plan.timezone,
              plan.expectedCachedAccountBalance == "0",
              let mode = operation.accountMode, ["aggregate", "units"].contains(mode),
              let quantityText = operation.quantity, let priceText = operation.unitPrice,
              let feeText = operation.fee, let priorText = operation.expectedPriorCash,
              let finalText = operation.expectedFinalCash,
              operation.feeCurrency == plan.currencyUnit,
              let quantity = try? canonicalDecimal(quantityText),
              let price = try? canonicalDecimal(priceText),
              let fee = try? canonicalDecimal(feeText),
              let prior = try? canonicalDecimal(priorText),
              let final = try? canonicalDecimal(finalText),
              fee >= 0, final == prior + parsedAmount else {
            throw HostError.message("W08 identity, currency, or derived cash is invalid")
        }
        let trade = kind == "investment_buy" || kind == "investment_sell"
        if trade {
            guard mode == "units", operation.cashEventType == nil,
                  operation.investmentSymbol == nil,
                  splits.isEmpty, let gid = operation.holdingGID, !isBlank(gid),
                  let symbol = operation.holdingSymbol, !isBlank(symbol),
                  let assetType = operation.assetType, assetType >= 0,
                  let unitsText = operation.expectedPriorUnits,
                  let finalUnitsText = operation.expectedFinalUnits,
                  let units = try? canonicalDecimal(unitsText),
                  let finalUnits = try? canonicalDecimal(finalUnitsText),
                  quantity > 0, price > 0, units >= 0, finalUnits >= 0,
                  finalUnits == units + (kind == "investment_buy" ? quantity : -quantity),
                  parsedAmount == (kind == "investment_buy" ? -(quantity * price + fee) : quantity * price - fee) else {
                throw HostError.message("W08 trade amount, asset, or units is invalid")
            }
        } else {
            let types: Set<String> = kind == "investment_income"
                ? ["dividend", "interest", "sale_proceeds", "other_income"]
                : ["fee", "other_expense"]
            guard let event = operation.cashEventType, types.contains(event),
                  splits.count == 1, operation.holdingGID == nil,
                  operation.holdingSymbol == nil, operation.assetType == nil,
                  operation.expectedPriorUnits == nil, operation.expectedFinalUnits == nil,
                  quantity == 0, price == 0, fee == 0 else {
                throw HostError.message("W08 cash event shape is invalid")
            }
            if let symbol = operation.investmentSymbol,
               isBlank(symbol) || symbol != symbol.trimmingCharacters(in: .whitespacesAndNewlines) {
                throw HostError.message("W08 investment symbol is invalid")
            }
        }
        for value in [amount, feeText, priorText, finalText] {
            let decimal = try canonicalDecimal(value)
            var source = decimal, rounded = Decimal()
            NSDecimalRound(&rounded, &source, 2, .plain)
            guard rounded == decimal else { throw HostError.message("W08 cash precision exceeds cents") }
        }
    }
}

// W02 scalar edits use the installed model-48 field types. Relationship edits and
// corrections to reconciled data require separately accepted contracts.
private let editFieldNames: [String: [String]] = [
    "amount": ["amount", "originalAmount"], "occurred_at": ["date"],
    "note": ["notes"], "description": ["desc"], "checkbook_number": ["checkbookNumber"],
]

func validateReconcileSourceScope(_ scope: ReconcileSourceScope?, raw: Any?, plan: WriterPlanV2) throws {
    guard let scope, let raw = raw as? [String: Any],
          Set(raw.keys) == ["scope", "read_status", "external_source_verified", "account_gid",
                            "currency_unit", "verified_balance", "source_count", "parsed_count", "transaction_gids"],
          scope.scope == "entire_account", scope.readStatus == "complete", scope.externalSourceVerified,
          scope.accountGID == plan.expectedAccountGID, scope.currencyUnit == plan.currencyUnit,
          scope.sourceCount == scope.transactionGIDs.count,
          scope.parsedCount == scope.transactionGIDs.count,
          !scope.transactionGIDs.isEmpty,
          scope.transactionGIDs == Array(Set(scope.transactionGIDs)).sorted(),
          scope.transactionGIDs.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: .whitespacesAndNewlines) }),
          try decimalValue(scope.verifiedBalance, field: "W04 verified balance") ==
            decimalValue(plan.expectedCachedAccountBalance, field: "W04 cached balance") else {
        throw HostError.message("W04 requires a complete, reviewed full-account source scope")
    }
    guard NSDecimalNumber(decimal: try decimalValue(scope.verifiedBalance, field: "W04 balance")).stringValue ==
            scope.verifiedBalance else {
        throw HostError.message("W04 verified balance must be canonical Decimal text")
    }
}

func validateReconcileOperationShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "account_gid", "owner_uri", "source_event_id", "expected_reconciled", "target_reconciled",
        "expected_native_status", "expected_native_flags", "correction_reason", "expected_balance_delta",
        "expected_postcondition", "allowed_changed_fields",
    ]
    let reconcile = plan.capability == "write.reconcile"
    let expectedKind = reconcile ? "reconcile_transaction" : "unreconcile_transaction"
    guard Set(raw.keys) == required,
          raw["kind"] as? String == expectedKind,
          raw["capability"] as? String == plan.capability,
          let entity = raw["transaction_entity"] as? String,
          ["DepositTransaction", "WithdrawTransaction", "RefundTransaction"].contains(entity),
          raw["account_gid"] as? String == plan.expectedAccountGID,
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["expected_reconciled"] as? Bool == !reconcile,
          raw["target_reconciled"] as? Bool == reconcile,
          let status = raw["expected_native_status"] as? Int, status == 1,
          let flags = raw["expected_native_flags"] as? Int, (0...32767).contains(flags),
          raw["expected_balance_delta"] as? String == "0",
          raw["allowed_changed_fields"] as? [String] == ["reconciled"],
          let post = raw["expected_postcondition"] as? [String: Any],
          Set(post.keys) == ["reconciled", "native_status", "native_flags", "expected_balance_delta"],
          post["reconciled"] as? Bool == reconcile,
          post["native_status"] as? Int == status,
          post["native_flags"] as? Int == flags,
          post["expected_balance_delta"] as? String == "0" else {
        throw HostError.message("W04 flag transition contains unsupported or unreviewed fields")
    }
    for key in ["operation_id", "transaction_gid", "account_gid", "owner_uri", "source_event_id"] {
        guard let value = raw[key] as? String, !isBlank(value),
              value == value.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw HostError.message("W04 identity text must be trimmed and nonblank")
        }
    }
    if reconcile {
        guard raw["correction_reason"] is NSNull else {
            throw HostError.message("W04 reconcile does not accept a correction reason")
        }
    } else {
        guard let reason = raw["correction_reason"] as? String,
              !isBlank(reason), reason == reason.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw HostError.message("W04 unreconcile requires a correction reason")
        }
    }
    guard plan.sourceScope?.transactionGIDs.contains(raw["transaction_gid"] as! String) == true else {
        throw HostError.message("W04 target is outside the verified account scope")
    }
}

func validateAssignmentOperationShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "account_gid", "owner_uri", "source_event_id", "currency_unit", "amount",
        "expected_assignments", "target", "replacement_mode", "expected_balance_delta",
        "expected_postcondition", "allowed_changed_fields",
    ]
    guard Set(raw.keys) == required,
          raw["capability"] as? String == "write.assign-payee-categories",
          plan.capability == "write.assign-payee-categories",
          let entity = raw["transaction_entity"] as? String,
          ["DepositTransaction", "WithdrawTransaction", "RefundTransaction"].contains(entity),
          raw["account_gid"] as? String == plan.expectedAccountGID,
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["currency_unit"] as? String == plan.currencyUnit,
          raw["replacement_mode"] as? String == "replace",
          raw["expected_balance_delta"] as? String == "0",
          raw["allowed_changed_fields"] as? [String] == ["payee", "categoriesAssigments"],
          let amountText = raw["amount"] as? String,
          let prior = raw["expected_assignments"] as? [String: Any],
          let target = raw["target"] as? [String: Any],
          let post = raw["expected_postcondition"] as? [String: Any],
          Set(post.keys) == ["payee_gid", "category_splits", "expected_balance_delta"],
          post["expected_balance_delta"] as? String == "0",
          NSDictionary(dictionary: target).isEqual(to: post.filter { $0.key != "expected_balance_delta" }) else {
        throw HostError.message("W03 assignment contains unsupported, missing, or unreviewed fields")
    }
    for key in ["operation_id", "transaction_gid", "account_gid", "owner_uri", "source_event_id"] {
        guard let value = raw[key] as? String, !isBlank(value),
              value == value.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw HostError.message("W03 identity text must be trimmed and nonblank")
        }
    }
    let amount = try decimalValue(amountText, field: "W03 amount")
    guard NSDecimalNumber(decimal: amount).stringValue == amountText,
          (entity == "WithdrawTransaction" ? amount < 0 : amount > 0) else {
        throw HostError.message("W03 amount must be a signed canonical Decimal")
    }
    func check(_ state: [String: Any]) throws {
        guard Set(state.keys) == ["payee_gid", "category_splits"],
              state["payee_gid"] is NSNull || state["payee_gid"] is String,
              let splits = state["category_splits"] as? [[String: Any]] else {
            throw HostError.message("W03 assignment state is incomplete")
        }
        if let gid = state["payee_gid"] as? String,
           isBlank(gid) || gid != gid.trimmingCharacters(in: .whitespacesAndNewlines) {
            throw HostError.message("W03 payee GID is invalid")
        }
        var total = Decimal.zero, ids: [String] = []
        for split in splits {
            guard Set(split.keys) == ["category_gid", "amount"],
                  let gid = split["category_gid"] as? String, !isBlank(gid),
                  gid == gid.trimmingCharacters(in: .whitespacesAndNewlines),
                  let text = split["amount"] as? String else {
                throw HostError.message("W03 category split is incomplete")
            }
            let value = try decimalValue(text, field: "W03 split")
            guard NSDecimalNumber(decimal: value).stringValue == text,
                  value != 0, (value > 0) == (amount > 0) else {
                throw HostError.message("W03 category split amount is invalid")
            }
            total += value
            ids.append(gid)
        }
        guard ids == ids.sorted(), Set(ids).count == ids.count,
              splits.isEmpty || total == amount else {
            throw HostError.message("W03 category splits must be sorted, unique, and sum to amount")
        }
    }
    try check(prior)
    try check(target)
    guard !NSDictionary(dictionary: prior).isEqual(to: target) else {
        throw HostError.message("W03 target does not change relationships")
    }
}

func validateEditOperationShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "account_gid", "owner_uri", "source_event_id", "currency_unit", "timezone",
        "changes", "expected_prior", "expected_balance_delta", "expected_postcondition",
        "allowed_changed_fields", "correction_mode",
    ]
    guard Set(raw.keys) == required,
          let changes = raw["changes"] as? [String: Any], !changes.isEmpty,
          let prior = raw["expected_prior"] as? [String: Any], Set(prior.keys) == Set(changes.keys),
          Set(changes.keys).isSubset(of: Set(editFieldNames.keys)),
          let entity = raw["transaction_entity"] as? String,
          ["DepositTransaction", "WithdrawTransaction", "RefundTransaction"].contains(entity),
          raw["capability"] as? String == "write.edit-transaction", plan.capability == "write.edit-transaction",
          raw["correction_mode"] as? String == "reject_reconciled",
          raw["account_gid"] as? String == plan.expectedAccountGID,
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["currency_unit"] as? String == plan.currencyUnit,
          raw["timezone"] as? String == plan.timezone,
          plan.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
          let delta = raw["expected_balance_delta"] as? String,
          let post = raw["expected_postcondition"] as? [String: Any],
          Set(post.keys) == ["fields", "expected_balance_delta"],
          let postFields = post["fields"] as? [String: Any],
          NSDictionary(dictionary: postFields).isEqual(to: changes),
          post["expected_balance_delta"] as? String == delta,
          raw["allowed_changed_fields"] as? [String] == changes.keys.flatMap({ editFieldNames[$0]! }).sorted() else {
        throw HostError.message("W02 edit contains unsupported, missing, or unreviewed fields")
    }
    for key in ["operation_id", "transaction_gid", "account_gid", "owner_uri", "source_event_id", "timezone"] {
        guard let s = raw[key] as? String, !isBlank(s), s == s.trimmingCharacters(in: .whitespacesAndNewlines) else {
            throw HostError.message("W02 identity text must be trimmed and nonblank")
        }
    }
    func canonicalDecimal(_ s: String) throws -> Decimal {
        let value = try decimalValue(s, field: "edit amount")
        guard NSDecimalNumber(decimal: value).stringValue == s else { throw HostError.message("W02 noncanonical Decimal") }
        return value
    }
    var expectedDelta = Decimal.zero
    for key in changes.keys {
        let old = prior[key]!, new = changes[key]!
        if key == "amount" {
            guard let o = old as? String, let n = new as? String else { throw HostError.message("W02 amount requires Decimal text") }
            let oldValue = try canonicalDecimal(o), newValue = try canonicalDecimal(n)
            guard oldValue != newValue,
                  entity == "WithdrawTransaction" ? (oldValue < 0 && newValue < 0) : (oldValue > 0 && newValue > 0) else {
                throw HostError.message("W02 amount sign or unchanged value is invalid")
            }
            expectedDelta = newValue - oldValue
        } else if key == "occurred_at" {
            guard let o = old as? String, let n = new as? String,
                  !o.contains("."), !n.contains("."), try planTimestamp(o) != planTimestamp(n) else {
                throw HostError.message("W02 date requires different whole-second timestamps")
            }
            for s in [o, n] {
                let instant = try planTimestamp(s)
                let suffix = s.suffix(6)
                let offset = s.hasSuffix("Z") ? 0 :
                    ((Int(suffix.dropFirst().prefix(2))! * 60 + Int(suffix.suffix(2))!) * 60 * (suffix.first == "-" ? -1 : 1))
                guard TimeZone(identifier: plan.timezone)?.secondsFromGMT(for: instant) == offset else {
                    throw HostError.message("W02 date offset differs from timezone")
                }
            }
        } else {
            for v in [old, new] {
                guard v is NSNull || v is String else { throw HostError.message("W02 text must be a string or null") }
                if let s = v as? String, isBlank(s) || s != s.trimmingCharacters(in: .whitespacesAndNewlines) {
                    throw HostError.message("W02 optional text must be trimmed and nonblank")
                }
            }
            guard !(old as! NSObject).isEqual(new) else { throw HostError.message("W02 requested field is unchanged") }
        }
    }
    guard try canonicalDecimal(delta) == expectedDelta else { throw HostError.message("W02 balance delta differs from edited amounts") }
}

func editFingerprint(_ object: NSManagedObject) throws -> [String: NSObject] {
    var fingerprint = try immutableTransactionFingerprint(object)
    if object.entity.relationshipsByName["payee"] != nil {
        fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
            .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
    }
    return fingerprint
}

func validateOrdinaryEditTarget(_ transaction: NSManagedObject, account: NSManagedObject,
                                currency: String) throws {
    guard ["DepositTransaction", "WithdrawTransaction", "RefundTransaction"].contains(transaction.entity.name ?? ""),
          (transaction.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
          transaction.value(forKey: "originalCurrency") as? String == currency,
          (transaction.value(forKey: "reconciled") as? NSNumber)?.boolValue == false,
          (transaction.value(forKey: "status") as? NSNumber)?.intValue == 1,
          (transaction.value(forKey: "flags") as? NSNumber)?.intValue == 0,
          (transaction.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
          transaction.value(forKey: "investmentHolding") == nil,
          transaction.value(forKey: "autoSkipLinkedScheduledTransactionGID") == nil,
          transaction.value(forKey: "investmentSymbol") == nil,
          transaction.value(forKey: "symbol") == nil,
          transaction.value(forKey: "originalFeeCurrency") == nil,
          try nativeDecimal(transaction, "originalExchangeRate") == 1 else {
        throw HostError.message("W02 requires an ordinary unreconciled same-account same-currency transaction")
    }
    for key in ["fee", "originalFee", "numberOfShares", "pricePerShare", "currencyExchangeRate"] {
        guard try nativeDecimal(transaction, key) == 0 else { throw HostError.message("W02 unsupported investment, fee, or FX state") }
    }
    let amount = try nativeDecimal(transaction, "amount")
    guard try nativeDecimal(transaction, "originalAmount") == amount,
          transaction.entity.name == "WithdrawTransaction" ? amount < 0 : amount > 0 else {
        throw HostError.message("W02 native amount or original amount is invalid")
    }
}

func editValueMatches(_ value: EditScalar, field: String, transaction: NSManagedObject) throws -> Bool {
    if field == "amount" {
        guard let s = value.string else { return false }
        return try nativeDecimal(transaction, "amount") == decimalValue(s, field: "edit amount")
    }
    if field == "occurred_at" {
        guard let s = value.string else { return false }
        return try transaction.value(forKey: "date") as? Date == planTimestamp(s)
    }
    let actual = transaction.value(forKey: editFieldNames[field]![0]) as? String
    // Swift String equality normalizes Unicode; the JSON contract compares the
    // exact requested text, including its scalar representation.
    guard let expected = value.string else { return actual == nil }
    guard let actual else { return false }
    return (actual as NSString).isEqual(to: expected)
}

// Validate complete existing and final refund graphs before mutating any object.
func validateEditRefundGraphs(_ transactions: [NSManagedObject], account: NSManagedObject,
                              plan: WriterPlanV2, proposed: [NSManagedObjectID: Decimal]) throws {
    var originals = Set<NSManagedObject>()
    for transaction in transactions {
        if transaction.entity.name == "WithdrawTransaction" { originals.insert(transaction) }
        if transaction.entity.name == "RefundTransaction" {
            let links = try relatedObjects(transaction, "withdrawTransactionsLinks")
            guard links.count == 1, let link = links.first,
                  link.entity.name == "WithdrawRefundTransactionLink",
                  (link.value(forKey: "refundTransaction") as? NSManagedObject)?.objectID == transaction.objectID,
                  let original = link.value(forKey: "withdrawTransaction") as? NSManagedObject,
                  original.entity.name == "WithdrawTransaction",
                  try relatedObjects(original, "refundTransactionsLinks").contains(link) else {
                throw HostError.message("W02 refund requires one unambiguous original withdrawal link")
            }
            originals.insert(original)
        }
    }
    for original in originals {
        try validateOrdinaryEditTarget(original, account: account, currency: plan.currencyUnit)
        var total = Decimal.zero, finalTotal = Decimal.zero
        var seen: Set<NSManagedObjectID> = []
        for link in try relatedObjects(original, "refundTransactionsLinks") {
            guard link.entity.name == "WithdrawRefundTransactionLink",
                  (link.value(forKey: "withdrawTransaction") as? NSManagedObject)?.objectID == original.objectID,
                  let refund = link.value(forKey: "refundTransaction") as? NSManagedObject,
                  refund.entity.name == "RefundTransaction", seen.insert(refund.objectID).inserted,
                  try relatedObjects(refund, "withdrawTransactionsLinks") == [link] else {
                throw HostError.message("W02 existing refund graph is ambiguous")
            }
            try validateOrdinaryEditTarget(refund, account: account, currency: plan.currencyUnit)
            let amount = try nativeDecimal(refund, "amount")
            total += amount
            finalTotal += proposed[refund.objectID] ?? amount
        }
        let amount = try nativeDecimal(original, "amount")
        guard total <= -amount, finalTotal <= -(proposed[original.objectID] ?? amount) else {
            throw HostError.message("W02 refund total exceeds original withdrawal")
        }
    }
}

struct EditInspection {
    let receipt: WriterResultV2
    let account: NSManagedObject
    let transactions: [NSManagedObject]
    let balanceAfter: Decimal
}

func inspectEdits(_ plan: WriterPlanV2, context: NSManagedObjectContext, saved: Bool = false) throws -> EditInspection {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W02 missing coordinator") }
    try requireCreationFixture(coordinator)
    let account = try fetchExactObject(entityName: "CashAccount", gid: plan.expectedAccountGID, context: context)
    // The metadata marker alone does not identify an invented W01 fixture.
    guard let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          owner.value(forKey: "syncLogin") as? String == "w01-fixture@example.invalid",
          account.value(forKey: "name") as? String == "W01",
          account.value(forKey: "currencyName") as? String == plan.currencyUnit,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil else {
        throw HostError.message("W02 requires an active same-owner same-currency disposable CashAccount")
    }
    var transactions: [NSManagedObject] = []
    var allOld = true, allNew = true
    var proposed: [NSManagedObjectID: Decimal] = [:]
    var delta = Decimal.zero
    for operation in plan.operations {
        let transaction = try fetchExactObject(entityName: operation.transactionEntity, gid: operation.transactionGID, context: context)
        try validateOrdinaryEditTarget(transaction, account: account, currency: plan.currencyUnit)
        guard operation.ownerURI == plan.ownerURI, operation.accountGID == plan.expectedAccountGID else {
            throw HostError.message("W02 transaction operation owner or account differs")
        }
        for (field, value) in operation.changes! {
            allNew = try editValueMatches(value, field: field, transaction: transaction) && allNew
            allOld = try editValueMatches(operation.expectedPrior![field]!, field: field, transaction: transaction) && allOld
        }
        if let newAmount = operation.changes!["amount"]?.string {
            guard try relatedObjects(transaction, "categoriesAssigments").isEmpty,
                  try relatedObjects(transaction, "budgetsLinks").isEmpty else {
                throw HostError.message("W02 amount edits with category or budget assignments require W03")
            }
            proposed[transaction.objectID] = try decimalValue(newAmount, field: "edited amount")
        }
        delta += try decimalValue(operation.expectedBalanceDelta!, field: "edit balance delta")
        transactions.append(transaction)
    }
    let before = try decimalValue(plan.expectedCachedAccountBalance, field: "cached balance")
    let after = before + delta
    _ = try decimalValue(NSDecimalNumber(decimal: after).stringValue, field: "resulting balance")
    let actualBalance = try nativeDecimal(account, "ballance")
    let classification: String
    if allNew && actualBalance == after { classification = saved ? "applied" : "noop" }
    else if allOld && actualBalance == before && !saved { classification = "retry_safe" }
    else { classification = "unknown" }
    try validateEditRefundGraphs(transactions, account: account, plan: plan, proposed: proposed)
    let success = classification == "applied" || classification == "noop"
    let operations = zip(plan.operations, transactions).map { operation, transaction in
        var result = WriterOperationResultV2(operationID: operation.operationID,
            status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
            transactionGID: operation.transactionGID, durableURI: transaction.objectID.uriRepresentation().absoluteString,
            durableNumericID: durableNumericID(transaction.objectID), oldPayeeGID: nil, newPayeeGID: nil, postcondition: nil)
        if success { result.editPostcondition = EditPostcondition(fields: operation.changes!, expectedBalanceDelta: operation.expectedBalanceDelta!) }
        return result
    }
    return EditInspection(receipt: WriterResultV2(contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
        classification: classification, verified: success, operations: operations), account: account,
        transactions: transactions, balanceAfter: after)
}

func editTransactionsV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                        requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let prior = try inspectEdits(plan, context: context)
    if prior.receipt.classification == "noop" { return prior.receipt }
    guard prior.receipt.classification == "retry_safe" else { throw HostError.message("W02 expected prior fields or account balance are stale; refusing replay") }
    var allowed: [NSManagedObjectID: Set<String>] = [:]
    for (operation, transaction) in zip(plan.operations, prior.transactions) {
        allowed[transaction.objectID] = Set(operation.allowedChangedFields!.map { "attribute:\($0)" })
    }
    if plan.operations.contains(where: { $0.changes?["amount"] != nil }) {
        allowed[prior.account.objectID] = ["attribute:ballance"]
    }
    // Snapshot every persisted object, including related assignments, accounts and history.
    var preimages: [CreationPreimage] = []
    for entity in context.persistentStoreCoordinator!.managedObjectModel.entities where entity.superentity == nil {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: entity.name!)) {
            let keys = allowed[object.objectID] ?? []
            preimages.append(CreationPreimage(objectID: object.objectID,
                fingerprint: try editFingerprint(object).filter { !keys.contains($0.key) }, allowedKeys: keys))
        }
    }
    for (operation, transaction) in zip(plan.operations, prior.transactions) {
        for (field, value) in operation.changes! {
            if field == "amount" {
                let number = nativeDouble(try decimalValue(value.string!, field: "edited amount"))
                transaction.setValue(number, forKey: "amount")
                transaction.setValue(number, forKey: "originalAmount")
            } else if field == "occurred_at" {
                transaction.setValue(try planTimestamp(value.string!), forKey: "date")
            } else { transaction.setValue(value.string, forKey: editFieldNames[field]![0]) }
        }
    }
    if allowed[prior.account.objectID] != nil { prior.account.setValue(nativeDouble(prior.balanceAfter), forKey: "ballance") }
    try verifyCreationPreimages(preimages, context: context)
    try requireStopped()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W02 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let persisted = try inspectEdits(plan, context: readback, saved: true)
            guard persisted.receipt.classification == "applied" else { throw HostError.message("W02 independent read-back differs") }
            try verifyCreationPreimages(preimages, context: readback)
            return persisted.receipt
        }
    }
    return try result.get()
}

struct ReconcileInspection {
    let receipt: WriterResultV2
    let transactions: [NSManagedObject]
}

func inspectReconciliation(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                           saved: Bool = false) throws -> ReconcileInspection {
    guard let coordinator = context.persistentStoreCoordinator, let scope = plan.sourceScope else {
        throw HostError.message("W04 missing coordinator or source scope")
    }
    try requireCreationFixture(coordinator)
    let account = try fetchExactObject(entityName: "CashAccount", gid: plan.expectedAccountGID, context: context)
    guard let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          owner.value(forKey: "syncLogin") as? String == "w01-fixture@example.invalid",
          account.value(forKey: "name") as? String == "W01",
          account.value(forKey: "currencyName") as? String == plan.currencyUnit,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil,
          try nativeDecimal(account, "ballance") == decimalValue(plan.expectedCachedAccountBalance, field: "W04 balance") else {
        throw HostError.message("W04 account identity, currency, or balance differs from reviewed scope")
    }
    // The root entity includes every transaction subtype, including transfers and
    // special records.  A matching subset is insufficient for a reconciliation.
    let accountTransactions = try context.fetch(NSFetchRequest<NSManagedObject>(entityName: "Transaction"))
        .filter { ($0.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID }
    let actualGIDs = accountTransactions.compactMap { $0.value(forKey: "GID") as? String }.sorted()
    guard actualGIDs.count == accountTransactions.count, actualGIDs == scope.transactionGIDs else {
        throw HostError.message("W04 account transaction inventory is incomplete or stale")
    }
    var transactions: [NSManagedObject] = []
    var allOld = true, allNew = true
    for operation in plan.operations {
        let transaction = try fetchExactObject(entityName: operation.transactionEntity,
                                               gid: operation.transactionGID, context: context)
        guard (transaction.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              transaction.entity.name == operation.transactionEntity,
              transaction.value(forKey: "originalCurrency") as? String == plan.currencyUnit,
              (transaction.value(forKey: "status") as? NSNumber)?.intValue == operation.expectedNativeStatus,
              (transaction.value(forKey: "flags") as? NSNumber)?.intValue == operation.expectedNativeFlags,
              (transaction.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              transaction.value(forKey: "investmentHolding") == nil,
              transaction.value(forKey: "autoSkipLinkedScheduledTransactionGID") == nil,
              transaction.value(forKey: "investmentSymbol") == nil,
              transaction.value(forKey: "symbol") == nil,
              transaction.value(forKey: "originalFeeCurrency") == nil,
              try nativeDecimal(transaction, "originalExchangeRate") == 1 else {
            throw HostError.message("W04 target has an unsupported native state or stale flags")
        }
        for key in ["fee", "originalFee", "numberOfShares", "pricePerShare", "currencyExchangeRate"] {
            guard try nativeDecimal(transaction, key) == 0 else {
                throw HostError.message("W04 investment, fee, or FX transaction is unsupported")
            }
        }
        let amount = try nativeDecimal(transaction, "amount")
        guard try nativeDecimal(transaction, "originalAmount") == amount,
              transaction.entity.name == "WithdrawTransaction" ? amount < 0 : amount > 0 else {
            throw HostError.message("W04 target amount or sign is invalid")
        }
        let reconciled = (transaction.value(forKey: "reconciled") as? NSNumber)?.boolValue
        guard let reconciled else { throw HostError.message("W04 target lacks native reconciled state") }
        allOld = allOld && reconciled == operation.expectedReconciled
        allNew = allNew && reconciled == operation.targetReconciled
        transactions.append(transaction)
    }
    let classification = allNew ? (saved ? "applied" : "noop") : allOld && !saved ? "retry_safe" : "unknown"
    let success = classification == "noop" || classification == "applied"
    let results = zip(plan.operations, transactions).map { operation, transaction in
        var result = WriterOperationResultV2(operationID: operation.operationID,
            status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
            transactionGID: operation.transactionGID,
            durableURI: transaction.objectID.uriRepresentation().absoluteString,
            durableNumericID: durableNumericID(transaction.objectID), oldPayeeGID: nil,
            newPayeeGID: nil, postcondition: nil)
        if success {
            result.reconcilePostcondition = ReconcilePostcondition(reconciled: operation.targetReconciled!,
                nativeStatus: operation.expectedNativeStatus!, nativeFlags: operation.expectedNativeFlags!,
                expectedBalanceDelta: "0")
        }
        return result
    }
    return ReconcileInspection(receipt: WriterResultV2(contractVersion: 2, planID: plan.planID,
        planDigest: plan.planDigest, classification: classification, verified: success, operations: results),
        transactions: transactions)
}

func reconcileTransactionsV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                             requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let prior = try inspectReconciliation(plan, context: context)
    if prior.receipt.classification == "noop" { return prior.receipt }
    guard prior.receipt.classification == "retry_safe" else {
        throw HostError.message("W04 stale or mixed reconciliation state; refusing replay")
    }
    let allowed = Dictionary(uniqueKeysWithValues: prior.transactions.map { ($0.objectID, Set(["attribute:reconciled"])) })
    var preimages: [CreationPreimage] = []
    for entity in context.persistentStoreCoordinator!.managedObjectModel.entities where entity.superentity == nil {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: entity.name!)) {
            let keys = allowed[object.objectID] ?? []
            preimages.append(CreationPreimage(objectID: object.objectID,
                fingerprint: try editFingerprint(object).filter { !keys.contains($0.key) }, allowedKeys: keys))
        }
    }
    for (operation, transaction) in zip(plan.operations, prior.transactions) {
        transaction.setValue(operation.targetReconciled!, forKey: "reconciled")
    }
    try verifyCreationPreimages(preimages, context: context)
    try requireStopped()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W04 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let persisted = try inspectReconciliation(plan, context: readback, saved: true)
            guard persisted.receipt.classification == "applied" else {
                throw HostError.message("W04 independent read-back differs")
            }
            try verifyCreationPreimages(preimages, context: readback)
            return persisted.receipt
        }
    }
    return try result.get()
}

struct AssignmentInspection {
    let receipt: WriterResultV2
    let account: NSManagedObject
    let transactions: [NSManagedObject]
    let categories: [[NSManagedObject]]
    let payees: [NSManagedObject?]
    let oldAssignments: [Set<NSManagedObject>]
}

func assignmentState(_ transaction: NSManagedObject, owner: NSManagedObject,
                     amount: Decimal) throws -> AssignmentState {
    let payee = transaction.value(forKey: "payee") as? NSManagedObject
    if let payee {
        guard payee.entity.name == "Payee",
              (payee.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID,
              payee.value(forKey: "GID") as? String != nil else {
            throw HostError.message("W03 existing payee has wrong owner or identity")
        }
    }
    var splits: [CategorySplit] = []
    var ids: Set<String> = []
    let assignments = try relatedObjects(transaction, "categoriesAssigments")
    for assignment in assignments {
        guard assignment.entity.name == "CategoryAssigment",
              (assignment.value(forKey: "transaction") as? NSManagedObject)?.objectID == transaction.objectID,
              assignment.value(forKey: "budget") == nil,
              assignment.value(forKey: "scheduledTransacition") == nil,
              assignment.value(forKey: "stringHistoryItem") == nil,
              let category = assignment.value(forKey: "category") as? NSManagedObject,
              category.entity.name == "Category",
              (category.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID,
              let gid = category.value(forKey: "GID") as? String,
              ids.insert(gid).inserted else {
            throw HostError.message("W03 existing category assignment is ambiguous or externally linked")
        }
        let value = try nativeDecimal(assignment, "amount")
        guard value != 0, (value > 0) == (amount > 0),
              (category.value(forKey: "type") as? NSNumber)?.intValue == (amount > 0 ? 2 : 1) else {
            throw HostError.message("W03 existing category assignment has invalid amount or type")
        }
        splits.append(CategorySplit(categoryGID: gid, amount: NSDecimalNumber(decimal: value).stringValue))
    }
    splits.sort { $0.categoryGID < $1.categoryGID }
    let splitTotal = try splits.reduce(Decimal.zero) {
        try $0 + decimalValue($1.amount, field: "W03 split")
    }
    guard splits.isEmpty || splitTotal == amount else {
        throw HostError.message("W03 existing category splits do not sum to transaction")
    }
    return AssignmentState(payeeGID: payee?.value(forKey: "GID") as? String, categorySplits: splits)
}

func inspectAssignments(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                        saved: Bool = false) throws -> AssignmentInspection {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W03 missing coordinator") }
    try requireCreationFixture(coordinator)
    let account = try fetchExactObject(entityName: "CashAccount", gid: plan.expectedAccountGID, context: context)
    guard let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          owner.value(forKey: "syncLogin") as? String == "w01-fixture@example.invalid",
          account.value(forKey: "name") as? String == "W01",
          account.value(forKey: "currencyName") as? String == plan.currencyUnit,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil else {
        throw HostError.message("W03 requires the invented same-owner CashAccount fixture")
    }
    try validateAccountGuards(account, plan: plan)
    var transactions: [NSManagedObject] = []
    var categories: [[NSManagedObject]] = []
    var payees: [NSManagedObject?] = []
    var oldAssignments: [Set<NSManagedObject>] = []
    var allOld = true, allNew = true
    for operation in plan.operations {
        let transaction = try fetchExactObject(entityName: operation.transactionEntity,
                                               gid: operation.transactionGID, context: context)
        try validateOrdinaryEditTarget(transaction, account: account, currency: plan.currencyUnit)
        guard operation.accountGID == plan.expectedAccountGID,
              operation.ownerURI == plan.ownerURI,
              let amountText = operation.amount,
              try nativeDecimal(transaction, "amount") == decimalValue(amountText, field: "W03 amount"),
              try relatedObjects(transaction, "budgetsLinks").isEmpty,
              let old = operation.expectedAssignments, let target = operation.target else {
            throw HostError.message("W03 transaction identity, amount, or budget relationship is stale")
        }
        let current = try assignmentState(transaction, owner: owner,
                                          amount: try nativeDecimal(transaction, "amount"))
        allOld = allOld && current == old
        allNew = allNew && current == target
        let selectedPayee = try target.payeeGID.map { try fetchExactObject(entityName: "Payee", gid: $0, context: context) }
        if let selectedPayee,
           (selectedPayee.value(forKey: "user") as? NSManagedObject)?.objectID != owner.objectID {
            throw HostError.message("W03 target payee belongs to another owner")
        }
        var selectedCategories: [NSManagedObject] = []
        for split in target.categorySplits {
            let category = try fetchExactObject(entityName: "Category", gid: split.categoryGID, context: context)
            guard (category.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID,
                  (category.value(forKey: "type") as? NSNumber)?.intValue == (try nativeDecimal(transaction, "amount") > 0 ? 2 : 1) else {
                throw HostError.message("W03 target category has wrong owner or type")
            }
            selectedCategories.append(category)
        }
        transactions.append(transaction)
        categories.append(selectedCategories)
        payees.append(selectedPayee)
        oldAssignments.append(try relatedObjects(transaction, "categoriesAssigments"))
    }
    try validateEditRefundGraphs(transactions, account: account, plan: plan, proposed: [:])
    let classification = allNew ? (saved ? "applied" : "noop") : (allOld && !saved ? "retry_safe" : "unknown")
    let success = classification == "applied" || classification == "noop"
    let results = zip(plan.operations, transactions).map { operation, transaction in
        var result = WriterOperationResultV2(operationID: operation.operationID,
            status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
            transactionGID: operation.transactionGID,
            durableURI: transaction.objectID.uriRepresentation().absoluteString,
            durableNumericID: durableNumericID(transaction.objectID), oldPayeeGID: nil,
            newPayeeGID: nil, postcondition: nil)
        if success, let target = operation.target {
            result.assignmentPostcondition = AssignmentPostcondition(
                payeeGID: target.payeeGID, categorySplits: target.categorySplits,
                expectedBalanceDelta: "0")
        }
        return result
    }
    return AssignmentInspection(receipt: WriterResultV2(contractVersion: 2, planID: plan.planID,
        planDigest: plan.planDigest, classification: classification, verified: success,
        operations: results), account: account, transactions: transactions,
        categories: categories, payees: payees, oldAssignments: oldAssignments)
}

func assignTransactionRelationshipsV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                                      requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let prior = try inspectAssignments(plan, context: context)
    if prior.receipt.classification == "noop" { return prior.receipt }
    guard prior.receipt.classification == "retry_safe" else {
        throw HostError.message("W03 expected assignments are stale; refusing replay")
    }
    let removed = Set(prior.oldAssignments.enumerated().flatMap { index, assignments in
        plan.operations[index].expectedAssignments!.categorySplits == plan.operations[index].target!.categorySplits
            ? [] : Array(assignments)
    })
    var allowed: [NSManagedObjectID: Set<String>] = [:]
    for (index, transaction) in prior.transactions.enumerated() {
        allowed[transaction.objectID] = ["relationship:payee"]
        if plan.operations[index].expectedAssignments!.categorySplits != plan.operations[index].target!.categorySplits {
            allowed[transaction.objectID, default: []].insert("relationship:categoriesAssigments")
        }
        let currentPayee = transaction.value(forKey: "payee") as? NSManagedObject
        for payee in [currentPayee, prior.payees[index]].compactMap({ $0 }) {
            allowed[payee.objectID, default: []].insert("relationship:transactions")
        }
        for assignment in prior.oldAssignments[index] where removed.contains(assignment) {
            if let category = assignment.value(forKey: "category") as? NSManagedObject {
                allowed[category.objectID, default: []].insert("relationship:categoryAssigments")
            }
        }
        if plan.operations[index].expectedAssignments!.categorySplits != plan.operations[index].target!.categorySplits {
            for category in prior.categories[index] {
                allowed[category.objectID, default: []].insert("relationship:categoryAssigments")
            }
        }
    }
    var preimages: [CreationPreimage] = []
    for entity in context.persistentStoreCoordinator!.managedObjectModel.entities where entity.superentity == nil {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: entity.name!)) where !removed.contains(object) {
            let keys = allowed[object.objectID] ?? []
            preimages.append(CreationPreimage(objectID: object.objectID,
                fingerprint: try editFingerprint(object).filter { !keys.contains($0.key) }, allowedKeys: keys))
        }
    }
    for (index, transaction) in prior.transactions.enumerated() {
        for assignment in prior.oldAssignments[index] where removed.contains(assignment) {
            context.delete(assignment)
        }
        transaction.setValue(prior.payees[index], forKey: "payee")
        if plan.operations[index].expectedAssignments!.categorySplits == plan.operations[index].target!.categorySplits {
            continue
        }
        for (number, category) in prior.categories[index].enumerated() {
            let assignment = NSEntityDescription.insertNewObject(forEntityName: "CategoryAssigment", into: context)
            let split = plan.operations[index].target!.categorySplits[number]
            assignment.setValue(nativeDouble(try decimalValue(split.amount, field: "W03 split")), forKey: "amount")
            assignment.setValue(number, forKey: "assigmentNumber")
            assignment.setValue(category, forKey: "category")
            assignment.setValue(transaction, forKey: "transaction")
        }
    }
    try requireStopped()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W03 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let persisted = try inspectAssignments(plan, context: readback, saved: true)
            guard persisted.receipt.classification == "applied" else {
                throw HostError.message("W03 independent read-back differs")
            }
            try verifyCreationPreimages(preimages, context: readback)
            for assignment in removed {
                if (try? readback.existingObject(with: assignment.objectID)) != nil {
                    throw HostError.message("W03 obsolete category assignment survived replacement")
                }
            }
            return persisted.receipt
        }
    }
    return try result.get()
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

func precisePlanTimestamp(_ value: String) throws -> Date {
    _ = try planTimestamp(value)
    guard let dot = value.firstIndex(of: ".") else { return try planTimestamp(value) }
    let tail = value[value.index(after: dot)...]
    let digits = tail.prefix(while: { $0.isNumber })
    guard !digits.isEmpty, let fraction = Double("0." + digits) else {
        throw HostError.message("W06 timestamp has invalid fractional seconds")
    }
    let wholeSecond = String(value[..<dot]) + String(tail.dropFirst(digits.count))
    return try planTimestamp(wholeSecond).addingTimeInterval(fraction)
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

struct AdjustBalanceInspection {
    let receipt: WriterResultV2
    let account: NSManagedObject
    let openingBalance: Decimal
}

func adjustBalancePostcondition(_ operation: WriterOperationV2) -> AdjustBalancePostcondition {
    AdjustBalancePostcondition(transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID, accountGID: operation.accountGID!,
        ownerURI: operation.ownerURI, balanceUnit: operation.balanceUnit!,
        expectedPriorBalance: operation.expectedPriorBalance!, targetBalance: operation.targetBalance!,
        expectedBalanceDelta: operation.expectedBalanceDelta!, currencyUnit: operation.currencyUnit!,
        occurredAt: operation.occurredAt!, timezone: operation.timezone!)
}

func inspectAdjustBalance(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                          saved: Bool = false) throws -> AdjustBalanceInspection {
    let operation = plan.operations[0]
    let account = try fetchExactObject(entityName: "InvestmentAccount", gid: plan.expectedAccountGID,
                                       context: context)
    guard let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          account.value(forKey: "currencyName") as? String == plan.currencyUnit,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil,
          try relatedObjects(account, "investmentHoldings").isEmpty,
          try relatedObjects(account, "investmentTotalValueHistory").isEmpty,
          try nativeDecimal(account, "ballance") == 0 else {
        throw HostError.message("W05 account identity or aggregate investment shape differs")
    }
    let opening = try nativeDecimal(account, "openingBalance")
    let transactions = try relatedObjects(account, "transactionsHistory")
    var sum: Decimal = 0
    var latest = Date.distantPast
    let ordered = transactions.sorted {
        ($0.value(forKey: "date") as? Date ?? .distantPast) <
            ($1.value(forKey: "date") as? Date ?? .distantPast)
    }
    for transaction in ordered {
        // Older native rows may be reconciled and retain FX metadata.
        guard transaction.entity.name == "ReconcileTransaction",
              (transaction.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              transaction.value(forKey: "investmentHolding") == nil,
              (transaction.value(forKey: "status") as? NSNumber)?.intValue == 2,
              (transaction.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              (transaction.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              transaction.value(forKey: "desc") as? String == "New balance",
              transaction.value(forKey: "payee") == nil,
              transaction.value(forKey: "investmentSymbol") == nil,
              transaction.value(forKey: "symbol") == nil,
              transaction.value(forKey: "originalFeeCurrency") == nil,
              try relatedObjects(transaction, "tags").isEmpty,
              try relatedObjects(transaction, "categoriesAssigments").isEmpty,
              try relatedObjects(transaction, "images").isEmpty,
              try nativeDecimal(transaction, "numberOfShares") == 0,
              try nativeDecimal(transaction, "reconcileNumberOfShares") == 0,
              try nativeDecimal(transaction, "fee") == 0,
              try nativeDecimal(transaction, "originalFee") == 0,
              try nativeDecimal(transaction, "originalExchangeRate") == 0,
              try nativeDecimal(transaction, "pricePerShare") == 0,
              let date = transaction.value(forKey: "date") as? Date else {
            throw HostError.message("W05 account history contains an unsupported transaction")
        }
        sum += try nativeDecimal(transaction, "amount")
        var rowBalance = opening + sum
        var roundedRowBalance = Decimal()
        NSDecimalRound(&roundedRowBalance, &rowBalance, 2, .plain)
        guard try nativeDecimal(transaction, "reconcileAmount") == roundedRowBalance else {
            throw HostError.message("W05 account history has an inconsistent adjustment balance")
        }
        guard date > latest else {
            throw HostError.message("W05 account history has ambiguous adjustment dates")
        }
        latest = date
    }
    var unrounded = opening + sum
    var actual = Decimal()
    NSDecimalRound(&actual, &unrounded, 2, .plain)
    let prior = try decimalValue(operation.expectedPriorBalance!, field: "prior balance")
    let target = try decimalValue(operation.targetBalance!, field: "target balance")
    let occurred = try planTimestamp(operation.occurredAt!)
    let candidates = try creationObjects(entity: "SyncObject", gid: operation.transactionGID, context: context)
    guard candidates.count <= 1 else { throw HostError.message("W05 duplicate GID collision") }
    let existing = candidates.first
    if let existing {
        guard existing.entity.name == "ReconcileTransaction",
              (existing.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              existing.value(forKey: "date") as? Date == occurred,
              existing.value(forKey: "desc") as? String == "New balance",
              existing.value(forKey: "notes") as? String == "",
              (existing.value(forKey: "status") as? NSNumber)?.intValue == 2,
              (existing.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              (existing.value(forKey: "reconciled") as? NSNumber)?.boolValue == false,
              existing.value(forKey: "investmentHolding") == nil,
              existing.value(forKey: "originalCurrency") == nil,
              existing.value(forKey: "originalFeeCurrency") == nil,
              existing.value(forKey: "investmentSymbol") == nil,
              existing.value(forKey: "symbol") == nil,
              existing.value(forKey: "payee") == nil,
              (existing.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              try relatedObjects(existing, "tags").isEmpty,
              try relatedObjects(existing, "categoriesAssigments").isEmpty,
              try relatedObjects(existing, "images").isEmpty,
              try nativeDecimal(existing, "amount") == target - prior,
              try nativeDecimal(existing, "reconcileAmount") == target,
              try nativeDecimal(existing, "numberOfShares") == 0,
              try nativeDecimal(existing, "reconcileNumberOfShares") == 0,
              try nativeDecimal(existing, "originalAmount") == 0,
              try nativeDecimal(existing, "fee") == 0,
              try nativeDecimal(existing, "originalFee") == 0,
              try nativeDecimal(existing, "currencyExchangeRate") == 0,
              try nativeDecimal(existing, "originalExchangeRate") == 0,
              try nativeDecimal(existing, "pricePerShare") == 0 else {
            throw HostError.message("W05 existing GID does not match the requested native adjustment")
        }
    }
    let classification: String
    if existing != nil && actual == target { classification = saved ? "applied" : "noop" }
    else if existing == nil && actual == target && prior == target { classification = "noop" }
    else if existing == nil && actual == prior && occurred > latest { classification = "retry_safe" }
    else { classification = "unknown" }
    let success = classification == "applied" || classification == "noop"
    var item = WriterOperationResultV2(operationID: operation.operationID,
        status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID,
        durableURI: existing?.objectID.uriRepresentation().absoluteString,
        durableNumericID: existing.map { durableNumericID($0.objectID) },
        oldPayeeGID: nil, newPayeeGID: nil, postcondition: nil)
    if success { item.adjustBalancePostcondition = adjustBalancePostcondition(operation) }
    return AdjustBalanceInspection(receipt: WriterResultV2(contractVersion: 2, planID: plan.planID,
        planDigest: plan.planDigest, classification: classification, verified: success,
        operations: [item]), account: account, openingBalance: opening)
}

func adjustBalanceV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                     requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let before = try inspectAdjustBalance(plan, context: context)
    if before.receipt.classification == "noop" { return before.receipt }
    guard before.receipt.classification == "retry_safe" else {
        throw HostError.message("W05 prior balance, date or GID is stale")
    }
    let previousHistory = try relatedObjects(before.account, "transactionsHistory")
    let preimages = try ([before.account] + Array(previousHistory)).map { object -> CreationPreimage in
        let allowed: Set<String> = object.objectID == before.account.objectID
            ? ["relationship:transactionsHistory"] : []
        var fingerprint = try immutableTransactionFingerprint(object)
        if object.entity.relationshipsByName["payee"] != nil {
            fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
        }
        return CreationPreimage(objectID: object.objectID,
            fingerprint: fingerprint.filter { !allowed.contains($0.key) }, allowedKeys: allowed)
    }
    let operation = plan.operations[0]
    let transaction = NSEntityDescription.insertNewObject(forEntityName: "ReconcileTransaction", into: context)
    transaction.setValue(operation.transactionGID, forKey: "GID")
    transaction.setValue(nativeDouble(try decimalValue(operation.expectedBalanceDelta!, field: "delta")), forKey: "amount")
    transaction.setValue(nativeDouble(try decimalValue(operation.targetBalance!, field: "target")), forKey: "reconcileAmount")
    transaction.setValue(try planTimestamp(operation.occurredAt!), forKey: "date")
    transaction.setValue(try planTimestamp(plan.createdAt), forKey: "objectCreationDate")
    transaction.setValue("New balance", forKey: "desc")
    transaction.setValue("", forKey: "notes")
    transaction.setValue(2, forKey: "status")
    transaction.setValue(before.account, forKey: "account")
    try verifyCreationPreimages(preimages, context: context)
    try requireStopped()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W05 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let verified = try inspectAdjustBalance(plan, context: readback, saved: true)
            guard verified.receipt.classification == "applied",
                  verified.openingBalance == before.openingBalance else {
                throw HostError.message("W05 independent read-back differs")
            }
            try verifyCreationPreimages(preimages, context: readback)
            return verified.receipt
        }
    }
    return try result.get()
}

struct DeletionInspection {
    let receipt: WriterResultV2
    let account: NSManagedObject
    let target: NSManagedObject?
    let history: [NSManagedObject]
}

func inspectDeleteAdjustment(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                             saved: Bool = false) throws -> DeletionInspection {
    guard let coordinator = context.persistentStoreCoordinator else {
        throw HostError.message("W06 missing coordinator")
    }
    try requireCreationFixture(coordinator)
    let operation = plan.operations[0]
    let account = try fetchExactObject(entityName: "InvestmentAccount", gid: plan.expectedAccountGID,
                                       context: context)
    guard let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          account.value(forKey: "currencyName") as? String == "GBP",
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil,
          try relatedObjects(account, "investmentHoldings").isEmpty,
          try relatedObjects(account, "investmentTotalValueHistory").isEmpty,
          try nativeDecimal(account, "ballance") == 0 else {
        throw HostError.message("W06 account identity or aggregate investment shape differs")
    }
    let opening = try nativeDecimal(account, "openingBalance")
    let history = try relatedObjects(account, "transactionsHistory").sorted {
        ($0.value(forKey: "date") as? Date ?? .distantPast) <
            ($1.value(forKey: "date") as? Date ?? .distantPast)
    }
    var total = opening
    var latest = Date.distantPast
    for transaction in history {
        guard transaction.entity.name == "ReconcileTransaction",
              (transaction.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              transaction.value(forKey: "investmentHolding") == nil,
              (transaction.value(forKey: "status") as? NSNumber)?.intValue == 2,
              (transaction.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              (transaction.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              transaction.value(forKey: "desc") as? String == "New balance",
              transaction.value(forKey: "payee") == nil,
              transaction.value(forKey: "investmentSymbol") == nil,
              transaction.value(forKey: "symbol") == nil,
              transaction.value(forKey: "originalFeeCurrency") == nil,
              try relatedObjects(transaction, "tags").isEmpty,
              try relatedObjects(transaction, "categoriesAssigments").isEmpty,
              try relatedObjects(transaction, "images").isEmpty,
              try nativeDecimal(transaction, "numberOfShares") == 0,
              try nativeDecimal(transaction, "reconcileNumberOfShares") == 0,
              try nativeDecimal(transaction, "fee") == 0,
              try nativeDecimal(transaction, "originalFee") == 0,
              try nativeDecimal(transaction, "originalExchangeRate") == 0,
              try nativeDecimal(transaction, "pricePerShare") == 0,
              let date = transaction.value(forKey: "date") as? Date,
              date > latest else {
            throw HostError.message("W06 account history contains an unsupported or ambiguous row")
        }
        total += try nativeDecimal(transaction, "amount")
        var source = total
        var rounded = Decimal()
        NSDecimalRound(&rounded, &source, 2, .plain)
        guard try nativeDecimal(transaction, "reconcileAmount") == rounded else {
            throw HostError.message("W06 account history has an inconsistent adjustment balance")
        }
        latest = date
    }
    var source = total
    var actual = Decimal()
    NSDecimalRound(&actual, &source, 2, .plain)
    let prior = try decimalValue(operation.expectedPriorBalance!, field: "W06 prior balance")
    let targetBalance = try decimalValue(operation.targetBalance!, field: "W06 target balance")
    let amount = try decimalValue(operation.expectedAmount!, field: "W06 target amount")
    let candidates = try creationObjects(entity: "SyncObject", gid: operation.transactionGID, context: context)
    guard candidates.count <= 1 else { throw HostError.message("W06 duplicate target GID") }
    let target = candidates.first
    if let target {
        let uri = target.objectID.uriRepresentation().absoluteString
        guard uri == "x-coredata://\(plan.storeIdentity.storeUUID)/ReconcileTransaction/p\(operation.transactionNumericID!)" else {
            throw HostError.message("W06 target Core Data URI differs from the reviewed identity")
        }
        let observedDate = target.value(forKey: "date") as? Date ?? .distantPast
        let expectedDate = try precisePlanTimestamp(operation.occurredAt!)
        let dateDifference = abs(observedDate.timeIntervalSince(expectedDate))
        guard dateDifference < 0.000001 else {
            throw HostError.message("W06 target date differs by \(dateDifference) seconds")
        }
        guard target.entity.name == "ReconcileTransaction",
              durableNumericID(target.objectID) == operation.transactionNumericID,
              history.last?.objectID == target.objectID,
              (target.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              target.value(forKey: "notes") as? String == "",
              (target.value(forKey: "reconciled") as? NSNumber)?.boolValue == false,
              target.value(forKey: "originalCurrency") == nil,
              try nativeDecimal(target, "amount") == amount,
              try nativeDecimal(target, "reconcileAmount") == prior,
              try nativeDecimal(target, "originalAmount") == 0,
              try nativeDecimal(target, "currencyExchangeRate") == 0 else {
            throw HostError.message("W06 target differs from the reviewed latest adjustment")
        }
        for (name, relationship) in target.entity.relationshipsByName where name != "account" {
            if name == "user" {
                guard (target.value(forKey: name) as? NSManagedObject)?.objectID == owner.objectID else {
                    throw HostError.message("W06 target owner differs")
                }
            } else if relationship.isToMany {
                guard try relatedObjects(target, name).isEmpty else {
                    throw HostError.message("W06 target has a dependent relationship")
                }
            } else if target.value(forKey: name) != nil {
                throw HostError.message("W06 target has a dependent relationship")
            }
        }
    }
    let classification: String
    if target != nil && actual == prior && actual - amount == targetBalance {
        classification = "retry_safe"
    } else if target == nil && actual == targetBalance {
        classification = saved ? "applied" : "noop"
    } else { classification = "unknown" }
    let success = classification == "applied" || classification == "noop"
    var item = WriterOperationResultV2(operationID: operation.operationID,
        status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID,
        durableURI: "x-coredata://\(plan.storeIdentity.storeUUID)/ReconcileTransaction/p\(operation.transactionNumericID!)",
        durableNumericID: operation.transactionNumericID,
        oldPayeeGID: nil, newPayeeGID: nil, postcondition: nil)
    if success {
        item.deleteAdjustmentPostcondition = DeleteAdjustmentPostcondition(
            transactionGID: operation.transactionGID, accountGID: plan.expectedAccountGID,
            targetBalance: operation.targetBalance!)
    }
    return DeletionInspection(receipt: WriterResultV2(contractVersion: 2, planID: plan.planID,
        planDigest: plan.planDigest, classification: classification, verified: success,
        operations: [item]), account: account, target: target, history: history)
}

func deleteAdjustmentV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                        requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let before = try inspectDeleteAdjustment(plan, context: context)
    if before.receipt.classification == "noop" { return before.receipt }
    guard before.receipt.classification == "retry_safe", let target = before.target else {
        throw HostError.message("W06 target or prior balance is stale")
    }
    let retained = [before.account] + before.history.filter { $0.objectID != target.objectID }
    let preimages = try retained.map { object -> CreationPreimage in
        let allowed: Set<String> = object.objectID == before.account.objectID
            ? ["relationship:transactionsHistory"] : []
        var fingerprint = try immutableTransactionFingerprint(object)
        if object.entity.relationshipsByName["payee"] != nil {
            fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
        }
        return CreationPreimage(objectID: object.objectID,
            fingerprint: fingerprint.filter { !allowed.contains($0.key) }, allowedKeys: allowed)
    }
    try requireStopped()
    context.delete(target)
    try verifyCreationPreimages(preimages, context: context)
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W06 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let verified = try inspectDeleteAdjustment(plan, context: readback, saved: true)
            guard verified.receipt.classification == "applied" else {
                throw HostError.message("W06 independent read-back differs")
            }
            try verifyCreationPreimages(preimages, context: readback)
            return verified.receipt
        }
    }
    return try result.get()
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

struct TransferInspection {
    let receipt: WriterResultV2
    let senderAccount: NSManagedObject
    let recipientAccount: NSManagedObject
    let oldSender: NSManagedObject?
    let oldRecipient: NSManagedObject?
}

func transferAccounts(_ plan: WriterPlanV2, context: NSManagedObjectContext)
    throws -> (NSManagedObject, NSManagedObject) {
    guard let coordinator = context.persistentStoreCoordinator,
          let destination = plan.destinationAccount else {
        throw HostError.message("W07 missing destination or store coordinator")
    }
    try requireCreationFixture(coordinator)
    let sender = try fetchExactObject(entityName: "CashAccount", gid: plan.expectedAccountGID, context: context)
    let recipient = try fetchExactObject(entityName: "CashAccount", gid: destination.accountGID, context: context)
    guard sender.objectID != recipient.objectID,
          let owner = sender.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          (recipient.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID,
          sender.value(forKey: "currencyName") as? String == plan.currencyUnit,
          recipient.value(forKey: "currencyName") as? String == destination.currencyUnit,
          (sender.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          (recipient.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          sender.value(forKey: "onlineBankAccount") == nil,
          recipient.value(forKey: "onlineBankAccount") == nil else {
        throw HostError.message("W07 requires two active same-owner cash accounts in the reviewed currencies")
    }
    return (sender, recipient)
}

func transferOldObject(_ row: TransferOldRow, account: NSManagedObject,
                       context: NSManagedObjectContext) throws -> NSManagedObject {
    let object = try fetchExactObject(entityName: row.transactionEntity,
        gid: row.transactionGID, context: context)
    guard object.entity.name == row.transactionEntity,
          durableNumericID(object.objectID) == row.transactionNumericID,
          (object.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
          try nativeDecimal(object, "amount") == decimalValue(row.amount, field: "W07 old amount"),
          try nativeDecimal(object, "originalAmount") == decimalValue(row.amount, field: "W07 old original amount"),
          try nativeDecimal(object, "fee") == 0,
          try nativeDecimal(object, "originalFee") == 0,
          object.value(forKey: "originalFeeCurrency") == nil,
          object.value(forKey: "originalCurrency") as? String == row.currencyUnit,
          (object.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
          object.value(forKey: "investmentSymbol") == nil,
          object.value(forKey: "symbol") == nil,
          try nativeDecimal(object, "numberOfShares") == 0,
          try nativeDecimal(object, "pricePerShare") == 0,
          try nativeDecimal(object, "originalExchangeRate") == 1,
          try nativeDecimal(object, "currencyExchangeRate") == 1,
          (object.value(forKey: "status") as? NSNumber)?.intValue == row.status,
          (object.value(forKey: "flags") as? NSNumber)?.intValue == row.flags,
          (object.value(forKey: "reconciled") as? NSNumber)?.boolValue == row.reconciled,
          object.value(forKey: "notes") as? String == row.note,
          object.value(forKey: "desc") as? String == row.description,
          payeeGID(object) == row.payeeGID,
          object.value(forKey: "investmentHolding") == nil,
          object.value(forKey: "autoSkipLinkedScheduledTransactionGID") == nil,
          try relatedObjects(object, "budgetsLinks").isEmpty,
          try relatedObjects(object, "images").isEmpty else {
        throw HostError.message("W07 imported row differs from the reviewed identity or has unsupported links")
    }
    if row.transactionEntity == "WithdrawTransaction" {
        guard try relatedObjects(object, "refundTransactionsLinks").isEmpty else {
            throw HostError.message("W07 withdrawal has linked refunds")
        }
    }
    let date = try precisePlanTimestamp(row.occurredAt)
    guard abs(((object.value(forKey: "date") as? Date) ?? .distantPast).timeIntervalSince(date)) < 0.000001 else {
        throw HostError.message("W07 imported date is stale")
    }
    let tagGIDs = try relatedObjects(object, "tags").map { tag -> String in
        guard let gid = tag.value(forKey: "GID") as? String,
              let owner = account.value(forKey: "user") as? NSManagedObject,
              (tag.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID else {
            throw HostError.message("W07 imported tag has no same-owner GID")
        }
        return gid
    }.sorted()
    guard tagGIDs == row.tagGIDs else { throw HostError.message("W07 imported tags are stale") }
    if let payee = object.value(forKey: "payee") as? NSManagedObject {
        guard let owner = account.value(forKey: "user") as? NSManagedObject,
              (payee.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID else {
            throw HostError.message("W07 imported payee belongs to another owner")
        }
    }
    let assignments = try relatedObjects(object, "categoriesAssigments")
    for assignment in assignments {
        guard assignment.entity.name == "CategoryAssigment",
              (assignment.value(forKey: "transaction") as? NSManagedObject)?.objectID == object.objectID,
              assignment.value(forKey: "budget") == nil,
              assignment.value(forKey: "scheduledTransacition") == nil,
              assignment.value(forKey: "stringHistoryItem") == nil,
              let category = assignment.value(forKey: "category") as? NSManagedObject,
              let owner = account.value(forKey: "user") as? NSManagedObject,
              (category.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID else {
            throw HostError.message("W07 imported category assignment has external links")
        }
    }
    guard assignments.map({ $0.objectID.uriRepresentation().absoluteString }).sorted() == row.categoryAssignmentURIs else {
        throw HostError.message("W07 imported category assignments are stale")
    }
    return object
}

func transferPostcondition(_ plan: WriterPlanV2, operation: WriterOperationV2) throws -> TransferPostcondition {
    let old = operation.sourceOld!
    let destination = plan.destinationAccount!
    let prior = try decimalValue(destination.expectedCachedBalance, field: "W07 recipient balance")
    let amount = try decimalValue(operation.recipientAmount!, field: "W07 recipient amount")
    let result = prior + (operation.destinationOld == nil ? amount : 0)
    return TransferPostcondition(
        oldSenderGID: old.transactionGID, oldSenderNumericID: old.transactionNumericID,
        oldRecipientGID: operation.destinationOld?.transactionGID,
        oldRecipientNumericID: operation.destinationOld?.transactionNumericID,
        senderGID: operation.transactionGID, recipientGID: operation.recipientTransactionGID!,
        senderAccountGID: plan.expectedAccountGID, recipientAccountGID: destination.accountGID,
        senderAmount: operation.senderAmount!, recipientAmount: operation.recipientAmount!,
        sendAt: operation.sendAt!, receiveAt: operation.receiveAt!,
        exchangeRate: operation.exchangeRate!, feeAmount: operation.feeAmount!,
        senderBalance: NSDecimalNumber(decimal: try decimalValue(plan.expectedCachedAccountBalance,
            field: "W07 sender balance")).stringValue,
        recipientBalance: NSDecimalNumber(decimal: result).stringValue)
}

func transferReceipt(_ plan: WriterPlanV2, operation: WriterOperationV2,
                     classification: String, sender: NSManagedObject? = nil,
                     recipient: NSManagedObject? = nil) throws -> WriterResultV2 {
    let success = classification == "applied" || classification == "noop"
    var item = WriterOperationResultV2(
        operationID: operation.operationID, status: success ? classification : "unknown",
        transactionEntity: "TransferWithdrawTransaction", transactionGID: operation.transactionGID,
        durableURI: success ? sender?.objectID.uriRepresentation().absoluteString : nil,
        durableNumericID: success ? sender.map { durableNumericID($0.objectID) } : nil,
        oldPayeeGID: nil, newPayeeGID: nil, postcondition: nil)
    if success, let recipient {
        item.transferPostcondition = try transferPostcondition(plan, operation: operation)
        item.transferDetails = TransferDetails(
            recipientGID: operation.recipientTransactionGID!,
            recipientNumericID: durableNumericID(recipient.objectID),
            recipientURI: recipient.objectID.uriRepresentation().absoluteString,
            oldSenderNumericID: operation.sourceOld!.transactionNumericID,
            oldRecipientNumericID: operation.destinationOld?.transactionNumericID)
    }
    return WriterResultV2(contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
        classification: classification, verified: success, operations: [item])
}

func verifyTransferPair(_ plan: WriterPlanV2, operation: WriterOperationV2,
                        sender: NSManagedObject, recipient: NSManagedObject,
                        senderAccount: NSManagedObject, recipientAccount: NSManagedObject) throws {
    let senderAmount = try decimalValue(operation.senderAmount!, field: "W07 sender amount")
    let recipientAmount = try decimalValue(operation.recipientAmount!, field: "W07 recipient amount")
    let rate = try decimalValue(operation.exchangeRate!, field: "W07 exchange rate")
    let senderOld = operation.sourceOld!
    let recipientOld = operation.destinationOld
    guard sender.entity.name == "TransferWithdrawTransaction",
          recipient.entity.name == "TransferDepositTransaction",
          sender.value(forKey: "GID") as? String == operation.transactionGID,
          recipient.value(forKey: "GID") as? String == operation.recipientTransactionGID,
          (sender.value(forKey: "account") as? NSManagedObject)?.objectID == senderAccount.objectID,
          (recipient.value(forKey: "account") as? NSManagedObject)?.objectID == recipientAccount.objectID,
          (sender.value(forKey: "recipientAccount") as? NSManagedObject)?.objectID == recipientAccount.objectID,
          (recipient.value(forKey: "senderAccount") as? NSManagedObject)?.objectID == senderAccount.objectID,
          (sender.value(forKey: "recipientTransaction") as? NSManagedObject)?.objectID == recipient.objectID,
          (recipient.value(forKey: "senderTransaction") as? NSManagedObject)?.objectID == sender.objectID,
          try nativeDecimal(sender, "amount") == senderAmount,
          try nativeDecimal(sender, "originalAmount") == senderAmount,
          try nativeDecimal(sender, "originalRecipientAmount") == recipientAmount,
          try nativeDecimal(recipient, "amount") == recipientAmount,
          try nativeDecimal(recipient, "originalAmount") == recipientAmount,
          try nativeDecimal(recipient, "originalSenderAmount") == senderAmount,
          try nativeDecimal(sender, "originalExchangeRate") == rate,
          try nativeDecimal(sender, "currencyExchangeRate") == rate,
          try nativeDecimal(recipient, "originalExchangeRate") == rate,
          try nativeDecimal(recipient, "currencyExchangeRate") == rate,
          try nativeDecimal(sender, "fee") == 0,
          try nativeDecimal(sender, "originalFee") == 0,
          try nativeDecimal(recipient, "fee") == 0,
          try nativeDecimal(recipient, "originalFee") == 0,
          sender.value(forKey: "originalFeeCurrency") == nil,
          recipient.value(forKey: "originalFeeCurrency") == nil,
          sender.value(forKey: "originalCurrency") as? String == plan.currencyUnit,
          sender.value(forKey: "originalRecipientCurrency") as? String == plan.destinationAccount!.currencyUnit,
          recipient.value(forKey: "originalCurrency") as? String == plan.destinationAccount!.currencyUnit,
          recipient.value(forKey: "originalSenderCurrency") as? String == plan.currencyUnit,
          (sender.value(forKey: "status") as? NSNumber)?.intValue == 2,
          (recipient.value(forKey: "status") as? NSNumber)?.intValue == 2,
          (sender.value(forKey: "flags") as? NSNumber)?.intValue == 0,
          (recipient.value(forKey: "flags") as? NSNumber)?.intValue == 0,
          (sender.value(forKey: "reconciled") as? NSNumber)?.boolValue == senderOld.reconciled,
          (recipient.value(forKey: "reconciled") as? NSNumber)?.boolValue == (recipientOld?.reconciled ?? false),
          sender.value(forKey: "notes") as? String == senderOld.note,
          sender.value(forKey: "desc") as? String == senderOld.description,
          recipient.value(forKey: "notes") as? String == recipientOld?.note,
          recipient.value(forKey: "desc") as? String == recipientOld?.description,
          payeeGID(sender) == senderOld.payeeGID,
          payeeGID(recipient) == recipientOld?.payeeGID,
          try relatedObjects(sender, "categoriesAssigments").isEmpty,
          try relatedObjects(recipient, "categoriesAssigments").isEmpty,
          try relatedObjects(sender, "budgetsLinks").isEmpty,
          try relatedObjects(recipient, "budgetsLinks").isEmpty,
          try relatedObjects(sender, "images").isEmpty,
          try relatedObjects(recipient, "images").isEmpty else {
        throw HostError.message("W07 reciprocal transfer pair differs from the reviewed fields")
    }
    let senderDate = try precisePlanTimestamp(operation.sendAt!)
    let recipientDate = try precisePlanTimestamp(operation.receiveAt!)
    guard abs(((sender.value(forKey: "date") as? Date) ?? .distantPast).timeIntervalSince(senderDate)) < 0.000001,
          abs(((recipient.value(forKey: "date") as? Date) ?? .distantPast).timeIntervalSince(recipientDate)) < 0.000001 else {
        throw HostError.message("W07 persisted Send/Receive dates differ")
    }
    for (object, expected) in [(sender, senderOld.tagGIDs), (recipient, recipientOld?.tagGIDs ?? [])] {
        let tags = try relatedObjects(object, "tags").map { $0.value(forKey: "GID") as? String ?? "" }.sorted()
        guard tags == expected else { throw HostError.message("W07 transfer tags differ") }
    }
}

func rejectAmbiguousDestination(_ operation: WriterOperationV2,
                                account: NSManagedObject,
                                context: NSManagedObjectContext) throws {
    guard operation.destinationOld == nil else { return }
    let request = NSFetchRequest<NSManagedObject>(entityName: "DepositTransaction")
    let candidateDate = try precisePlanTimestamp(operation.receiveAt!)
    let amount = try decimalValue(operation.recipientAmount!, field: "W07 recipient amount")
    for candidate in try context.fetch(request) where
        (candidate.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID {
        if try nativeDecimal(candidate, "amount") == amount,
           let date = candidate.value(forKey: "date") as? Date,
           abs(date.timeIntervalSince(candidateDate)) <= 86400 {
            throw HostError.message("W07 destination has an ambiguous imported counterpart")
        }
    }
}

func inspectTransfer(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                     saved: Bool = false) throws -> TransferInspection {
    let operation = plan.operations[0]
    let (senderAccount, recipientAccount) = try transferAccounts(plan, context: context)
    let oldSource = try creationObjects(entity: "SyncObject", gid: operation.sourceOld!.transactionGID, context: context)
    let oldRecipient = try operation.destinationOld.map {
        try creationObjects(entity: "SyncObject", gid: $0.transactionGID, context: context)
    } ?? []
    let newSender = try creationObjects(entity: "SyncObject", gid: operation.transactionGID, context: context)
    let newRecipient = try creationObjects(entity: "SyncObject", gid: operation.recipientTransactionGID!, context: context)
    guard [oldSource, oldRecipient, newSender, newRecipient].allSatisfy({ $0.count <= 1 }) else {
        throw HostError.message("W07 duplicate old or new GID")
    }
    let sourcePrior = try decimalValue(plan.expectedCachedAccountBalance, field: "W07 source balance")
    let destinationPrior = try decimalValue(plan.destinationAccount!.expectedCachedBalance,
        field: "W07 destination balance")
    let recipientAmount = try decimalValue(operation.recipientAmount!, field: "W07 recipient amount")
    let destinationFinal = destinationPrior + (operation.destinationOld == nil ? recipientAmount : 0)
    let senderBalance = try nativeDecimal(senderAccount, "ballance")
    let recipientBalance = try nativeDecimal(recipientAccount, "ballance")
    let before = oldSource.count == 1 && oldRecipient.count == (operation.destinationOld == nil ? 0 : 1)
        && newSender.isEmpty && newRecipient.isEmpty
        && senderBalance == sourcePrior && recipientBalance == destinationPrior
    if before {
        let source = try transferOldObject(operation.sourceOld!, account: senderAccount, context: context)
        let recipient = try operation.destinationOld.map {
            try transferOldObject($0, account: recipientAccount, context: context)
        }
        try rejectAmbiguousDestination(operation, account: recipientAccount, context: context)
        guard !saved else { throw HostError.message("W07 persisted transfer is missing") }
        return TransferInspection(receipt: try transferReceipt(plan, operation: operation,
            classification: "retry_safe"), senderAccount: senderAccount,
            recipientAccount: recipientAccount, oldSender: source, oldRecipient: recipient)
    }
    let after = oldSource.isEmpty && oldRecipient.isEmpty && newSender.count == 1 && newRecipient.count == 1
        && senderBalance == sourcePrior && recipientBalance == destinationFinal
    if after {
        try rejectAmbiguousDestination(operation, account: recipientAccount, context: context)
        let remainingAssignments = Set(try context.fetch(
            NSFetchRequest<NSManagedObject>(entityName: "CategoryAssigment")
        ).map { $0.objectID.uriRepresentation().absoluteString })
        let oldAssignmentURIs = Set(operation.sourceOld!.categoryAssignmentURIs
            + (operation.destinationOld?.categoryAssignmentURIs ?? []))
        guard remainingAssignments.isDisjoint(with: oldAssignmentURIs) else {
            throw HostError.message("W07 old category assignments survived conversion")
        }
        let sender = newSender[0], recipient = newRecipient[0]
        try verifyTransferPair(plan, operation: operation, sender: sender, recipient: recipient,
            senderAccount: senderAccount, recipientAccount: recipientAccount)
        return TransferInspection(receipt: try transferReceipt(plan, operation: operation,
            classification: saved ? "applied" : "noop", sender: sender, recipient: recipient),
            senderAccount: senderAccount, recipientAccount: recipientAccount,
            oldSender: nil, oldRecipient: nil)
    }
    return TransferInspection(receipt: try transferReceipt(plan, operation: operation,
        classification: "unknown"), senderAccount: senderAccount,
        recipientAccount: recipientAccount, oldSender: nil, oldRecipient: nil)
}

func transferPreimages(_ inspection: TransferInspection,
                       context: NSManagedObjectContext) throws -> [CreationPreimage] {
    let oldRows = [inspection.oldSender, inspection.oldRecipient].compactMap { $0 }
    let oldIDs = Set(oldRows.map(\.objectID))
    let oldAssignments = try oldRows.reduce(into: Set<NSManagedObjectID>()) { ids, row in
        ids.formUnion(try relatedObjects(row, "categoriesAssigments").map(\.objectID))
    }
    var relatedIDs = Set<NSManagedObjectID>()
    var categoryIDs = Set<NSManagedObjectID>()
    for row in oldRows {
        if let payee = row.value(forKey: "payee") as? NSManagedObject { relatedIDs.insert(payee.objectID) }
        relatedIDs.formUnion(try relatedObjects(row, "tags").map(\.objectID))
        for assignment in try relatedObjects(row, "categoriesAssigments") {
            if let category = assignment.value(forKey: "category") as? NSManagedObject {
                categoryIDs.insert(category.objectID)
            }
        }
    }
    var preimages: [CreationPreimage] = []
    for name in ["SyncObject", "CategoryAssigment"] {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: name)) {
            if oldIDs.contains(object.objectID) || oldAssignments.contains(object.objectID) { continue }
            var allowed: Set<String> = []
            if object.objectID == inspection.senderAccount.objectID {
                allowed = ["relationship:transactionsHistory", "relationship:reverseTransferDepositTransactionSenderAccount"]
            }
            if object.objectID == inspection.recipientAccount.objectID {
                allowed = ["attribute:ballance", "relationship:transactionsHistory",
                    "relationship:reverseTransferWithdrawTransactionrecipientAccount"]
            }
            if relatedIDs.contains(object.objectID) { allowed.insert("relationship:transactions") }
            if categoryIDs.contains(object.objectID) { allowed.insert("relationship:categoryAssigments") }
            var fingerprint = try immutableTransactionFingerprint(object)
            if object.entity.relationshipsByName["payee"] != nil {
                fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                    .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
            }
            preimages.append(CreationPreimage(objectID: object.objectID,
                fingerprint: fingerprint.filter { !allowed.contains($0.key) }, allowedKeys: allowed))
        }
    }
    return preimages
}

func replaceImportWithTransferV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                                 requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let before = try inspectTransfer(plan, context: context)
    if before.receipt.classification == "noop" { return before.receipt }
    guard before.receipt.classification == "retry_safe", let oldSender = before.oldSender else {
        throw HostError.message("W07 old rows, new pair or account balances are stale")
    }
    let operation = plan.operations[0]
    let preimages = try transferPreimages(before, context: context)
    let oldRecipient = before.oldRecipient
    let senderTags = try Array(relatedObjects(oldSender, "tags"))
    let recipientTags = try oldRecipient.map { try Array(relatedObjects($0, "tags")) } ?? []
    let senderPayee = oldSender.value(forKey: "payee") as? NSManagedObject
    let recipientPayee = oldRecipient?.value(forKey: "payee") as? NSManagedObject
    let senderAmount = try decimalValue(operation.senderAmount!, field: "W07 sender amount")
    let recipientAmount = try decimalValue(operation.recipientAmount!, field: "W07 recipient amount")
    let rate = try decimalValue(operation.exchangeRate!, field: "W07 exchange rate")
    try requireStopped()
    let sender = NSEntityDescription.insertNewObject(forEntityName: "TransferWithdrawTransaction", into: context)
    let recipient = NSEntityDescription.insertNewObject(forEntityName: "TransferDepositTransaction", into: context)
    let created = try precisePlanTimestamp(plan.createdAt)
    sender.setValue(operation.transactionGID, forKey: "GID")
    sender.setValue(nativeDouble(senderAmount), forKey: "amount")
    sender.setValue(nativeDouble(senderAmount), forKey: "originalAmount")
    sender.setValue(nativeDouble(recipientAmount), forKey: "originalRecipientAmount")
    sender.setValue(plan.currencyUnit, forKey: "originalCurrency")
    sender.setValue(plan.destinationAccount!.currencyUnit, forKey: "originalRecipientCurrency")
    sender.setValue(nativeDouble(rate), forKey: "originalExchangeRate")
    sender.setValue(nativeDouble(rate), forKey: "currencyExchangeRate")
    sender.setValue(0.0, forKey: "fee")
    sender.setValue(0.0, forKey: "originalFee")
    sender.setValue(try precisePlanTimestamp(operation.sendAt!), forKey: "date")
    sender.setValue(created, forKey: "objectCreationDate")
    sender.setValue(2, forKey: "status")
    sender.setValue(0, forKey: "flags")
    sender.setValue(operation.sourceOld!.reconciled, forKey: "reconciled")
    sender.setValue(operation.sourceOld!.note, forKey: "notes")
    sender.setValue(operation.sourceOld!.description, forKey: "desc")
    sender.setValue(senderPayee, forKey: "payee")
    sender.setValue(NSSet(array: senderTags), forKey: "tags")
    sender.setValue(before.senderAccount, forKey: "account")
    sender.setValue(before.recipientAccount, forKey: "recipientAccount")
    sender.setValue(recipient, forKey: "recipientTransaction")

    recipient.setValue(operation.recipientTransactionGID!, forKey: "GID")
    recipient.setValue(nativeDouble(recipientAmount), forKey: "amount")
    recipient.setValue(nativeDouble(recipientAmount), forKey: "originalAmount")
    recipient.setValue(nativeDouble(senderAmount), forKey: "originalSenderAmount")
    recipient.setValue(plan.destinationAccount!.currencyUnit, forKey: "originalCurrency")
    recipient.setValue(plan.currencyUnit, forKey: "originalSenderCurrency")
    recipient.setValue(nativeDouble(rate), forKey: "originalExchangeRate")
    recipient.setValue(nativeDouble(rate), forKey: "currencyExchangeRate")
    recipient.setValue(0.0, forKey: "fee")
    recipient.setValue(0.0, forKey: "originalFee")
    recipient.setValue(try precisePlanTimestamp(operation.receiveAt!), forKey: "date")
    recipient.setValue(created, forKey: "objectCreationDate")
    recipient.setValue(2, forKey: "status")
    recipient.setValue(0, forKey: "flags")
    recipient.setValue(operation.destinationOld?.reconciled ?? false, forKey: "reconciled")
    recipient.setValue(operation.destinationOld?.note, forKey: "notes")
    recipient.setValue(operation.destinationOld?.description, forKey: "desc")
    recipient.setValue(recipientPayee, forKey: "payee")
    recipient.setValue(NSSet(array: recipientTags), forKey: "tags")
    recipient.setValue(before.recipientAccount, forKey: "account")
    recipient.setValue(before.senderAccount, forKey: "senderAccount")
    recipient.setValue(sender, forKey: "senderTransaction")
    context.delete(oldSender)
    if let oldRecipient { context.delete(oldRecipient) }
    if oldRecipient == nil {
        let balance = try decimalValue(plan.destinationAccount!.expectedCachedBalance,
            field: "W07 destination balance") + recipientAmount
        before.recipientAccount.setValue(nativeDouble(balance), forKey: "ballance")
    }
    try verifyCreationPreimages(preimages, context: context)
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W07 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let verified = try inspectTransfer(plan, context: readback, saved: true)
            guard verified.receipt.classification == "applied" else {
                throw HostError.message("W07 independent read-back differs")
            }
            try verifyCreationPreimages(preimages, context: readback)
            return verified.receipt
        }
    }
    return try result.get()
}

func recoverPlanV2(_ plan: WriterPlanV2, container: NSPersistentContainer) throws -> WriterResultV2 {
    let context = container.newBackgroundContext()
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("writer v2 recovery did not run"))
    context.performAndWait {
        do {
            if plan.capability == "write.edit-transaction" {
                result = .success(try inspectEdits(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.assign-payee-categories" {
                result = .success(try inspectAssignments(plan, context: context).receipt)
                return
            }
            if ["write.reconcile", "write.unreconcile"].contains(plan.capability) {
                result = .success(try inspectReconciliation(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.adjust-balance-investment-total" {
                result = .success(try inspectAdjustBalance(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.delete-adjust-balance-investment-total" {
                result = .success(try inspectDeleteAdjustment(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.replace-import-with-transfer" {
                result = .success(try inspectTransfer(plan, context: context).receipt)
                return
            }
            if let operation = plan.operations.first, operation.kind.hasPrefix("investment_") {
                result = .success(try inspectInvestment(operation, plan: plan, context: context))
                return
            }
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
            if plan.capability == "write.edit-transaction" {
                result = .success(try editTransactionsV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.assign-payee-categories" {
                result = .success(try assignTransactionRelationshipsV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if ["write.reconcile", "write.unreconcile"].contains(plan.capability) {
                result = .success(try reconcileTransactionsV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.adjust-balance-investment-total" {
                result = .success(try adjustBalanceV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.delete-adjust-balance-investment-total" {
                result = .success(try deleteAdjustmentV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.replace-import-with-transfer" {
                result = .success(try replaceImportWithTransferV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if let operation = plan.operations.first, operation.kind.hasPrefix("investment_") {
                result = .success(try createInvestmentV2(operation, plan: plan, context: context,
                    requireStopped: requireStopped))
                return
            }
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
    var holding: NSManagedObject? = nil
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
    var expectedFixed = fixed
    if operation.kind.hasPrefix("investment_") {
        let trade = operation.kind == "investment_buy" || operation.kind == "investment_sell"
        expectedFixed["status"] = 2
        expectedFixed["flags"] = 0
        expectedFixed["reconciled"] = true
        expectedFixed["currencyExchangeRate"] = trade ? 0.0 : 1.0
        expectedFixed["originalExchangeRate"] = trade ? 0.0 : 1.0
        expectedFixed["investmentSymbol"] = operation.investmentSymbol as Any? ?? NSNull()
    }
    if operation.kind == "investment_buy" || operation.kind == "investment_sell" {
        expectedFixed["numberOfShares"] = nativeDouble(try decimalValue(operation.quantity!, field: "W08 quantity"))
        expectedFixed["pricePerShare"] = nativeDouble(try decimalValue(operation.unitPrice!, field: "W08 price"))
        expectedFixed["fee"] = nativeDouble(try decimalValue(operation.fee!, field: "W08 fee"))
        expectedFixed["symbol"] = operation.holdingSymbol!
    }
    guard transaction.entity.name == operation.transactionEntity else { throw HostError.message("W01 source identity collision") }
    for (key, attribute) in transaction.entity.attributesByName {
        let expected = expectedFixed[key] ?? attribute.defaultValue ?? NSNull()
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
    let scalarRefs: [String: NSManagedObject?] = ["account": references.account, "payee": references.payee,
        "investmentHolding": references.holding]
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
            if object.objectID == refs.holding?.objectID { allowed.insert("relationship:investmentTransactions") }
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

func investmentDetails(_ operation: WriterOperationV2) -> InvestmentDetails {
    InvestmentDetails(accountMode: operation.accountMode!, cashEventType: operation.cashEventType,
        investmentSymbol: operation.investmentSymbol,
        holdingGID: operation.holdingGID, holdingSymbol: operation.holdingSymbol,
        assetType: operation.assetType, quantity: operation.quantity!, unitPrice: operation.unitPrice!,
        fee: operation.fee!, feeCurrency: operation.feeCurrency!,
        expectedPriorCash: operation.expectedPriorCash!, expectedFinalCash: operation.expectedFinalCash!,
        expectedPriorUnits: operation.expectedPriorUnits, expectedFinalUnits: operation.expectedFinalUnits)
}

func investmentLedger(_ account: NSManagedObject) throws -> Decimal {
    var total = try nativeDecimal(account, "openingBalance")
    for row in try relatedObjects(account, "transactionsHistory") {
        guard (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0 else {
            throw HostError.message("W08 account ledger contains a void row")
        }
        total += try nativeDecimal(row, "amount")
    }
    return total
}

func investmentUnits(_ holding: NSManagedObject, account: NSManagedObject) throws -> Decimal {
    var total = try nativeDecimal(holding, "openningNumberOfShares")
    for row in try relatedObjects(holding, "investmentTransactions") {
        guard (row.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              let entity = row.entity.name,
              ["InvestmentBuyTransaction", "InvestmentSellTransaction"].contains(entity) else {
            throw HostError.message("W08 holding history contains unsupported transaction")
        }
        let quantity = try nativeDecimal(row, "numberOfShares")
        guard quantity > 0 else { throw HostError.message("W08 holding history has nonpositive units") }
        total += entity == "InvestmentBuyTransaction" ? quantity : -quantity
    }
    guard total >= 0 else { throw HostError.message("W08 holding has negative derived units") }
    return total
}

func preflightInvestment(_ operation: WriterOperationV2, plan: WriterPlanV2,
                         context: NSManagedObjectContext, alreadyPresent: Bool) throws -> CreationReferences {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W08 missing coordinator") }
    try requireCreationFixture(coordinator)
    let account = try fetchExactObject(entityName: "InvestmentAccount", gid: plan.expectedAccountGID,
                                       context: context)
    guard let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == plan.ownerURI,
          account.value(forKey: "currencyName") as? String == plan.currencyUnit,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false,
          account.value(forKey: "onlineBankAccount") == nil,
          try nativeDecimal(account, "ballance") == 0 else {
        throw HostError.message("W08 requires an active same-owner InvestmentAccount with untouched cache")
    }
    let holdings = try relatedObjects(account, "investmentHoldings")
    if operation.accountMode == "aggregate" && !holdings.isEmpty {
        throw HostError.message("W08 aggregate account unexpectedly has holdings")
    }
    if operation.accountMode == "units" && holdings.isEmpty {
        throw HostError.message("W08 units account has no holdings")
    }
    let amount = try decimalValue(operation.amount!, field: "W08 amount")
    let prior = try decimalValue(operation.expectedPriorCash!, field: "W08 prior ledger")
    let final = try decimalValue(operation.expectedFinalCash!, field: "W08 final ledger")
    guard try investmentLedger(account) == (alreadyPresent ? final : prior) else {
        throw HostError.message("W08 investment ledger is stale")
    }
    func owned(_ entity: String, _ gid: String) throws -> NSManagedObject {
        let object = try fetchExactObject(entityName: entity, gid: gid, context: context)
        guard (object.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID else {
            throw HostError.message("W08 \(entity) owner mismatch")
        }
        return object
    }
    let payee = try operation.payeeGID.map { try owned("Payee", $0) }
    let tags = try (operation.tagGIDs ?? []).map { try owned("Tag", $0) }
    let categories = try (operation.categorySplits ?? []).map { split -> NSManagedObject in
        let category = try owned("Category", split.categoryGID)
        let expectedType = operation.kind == "investment_income" ? 2 : 1
        guard (category.value(forKey: "type") as? NSNumber)?.intValue == expectedType else {
            throw HostError.message("W08 cash category type differs from transaction")
        }
        return category
    }
    var holding: NSManagedObject?
    if let gid = operation.holdingGID {
        let selected = try fetchExactObject(entityName: "InvestmentHolding", gid: gid, context: context)
        guard holdings.contains(selected),
              (selected.value(forKey: "investmentAccount") as? NSManagedObject)?.objectID == account.objectID,
              selected.value(forKey: "symbol") as? String == operation.holdingSymbol,
              (selected.value(forKey: "investmentObjectType") as? NSNumber)?.intValue == operation.assetType,
              try investmentUnits(selected, account: account) == decimalValue(
                alreadyPresent ? operation.expectedFinalUnits! : operation.expectedPriorUnits!, field: "W08 units") else {
            throw HostError.message("W08 holding identity or derived units are stale")
        }
        holding = selected
    }
    return CreationReferences(account: account, payee: payee, categories: categories, tags: tags,
        original: nil, amount: amount, balanceAfter: final, holding: holding)
}

func investmentReceipt(_ operation: WriterOperationV2, plan: WriterPlanV2,
                       classification: String, objectID: NSManagedObjectID?) -> WriterResultV2 {
    let success = classification == "applied" || classification == "noop"
    var item = WriterOperationResultV2(operationID: operation.operationID,
        status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID, durableURI: objectID?.uriRepresentation().absoluteString,
        durableNumericID: objectID.map(durableNumericID), oldPayeeGID: nil, newPayeeGID: nil,
        postcondition: success ? creationPostcondition(operation) : nil)
    if success { item.investmentDetails = investmentDetails(operation) }
    return WriterResultV2(contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
        classification: classification, verified: success, operations: [item])
}

func inspectInvestment(_ operation: WriterOperationV2, plan: WriterPlanV2,
                       context: NSManagedObjectContext, saved: Bool = false) throws -> WriterResultV2 {
    let existing = try creationObjects(entity: "SyncObject", gid: operation.transactionGID, context: context)
    guard existing.count <= 1 else { throw HostError.message("W08 source identity is ambiguous") }
    let refs = try preflightInvestment(operation, plan: plan, context: context, alreadyPresent: !existing.isEmpty)
    guard let transaction = existing.first else {
        guard !saved else { throw HostError.message("W08 persisted transaction is missing") }
        return investmentReceipt(operation, plan: plan, classification: "retry_safe", objectID: nil)
    }
    try verifyCreatedTransaction(transaction, operation: operation, plan: plan, references: refs)
    return investmentReceipt(operation, plan: plan, classification: saved ? "applied" : "noop",
                             objectID: transaction.objectID)
}

func createInvestmentV2(_ operation: WriterOperationV2, plan: WriterPlanV2,
                        context: NSManagedObjectContext,
                        requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let prior = try inspectInvestment(operation, plan: plan, context: context)
    if prior.classification == "noop" { return prior }
    let refs = try preflightInvestment(operation, plan: plan, context: context, alreadyPresent: false)
    let preimages = try creationPreimages(refs, context: context)
    let row = NSEntityDescription.insertNewObject(forEntityName: operation.transactionEntity, into: context)
    row.setValue(operation.transactionGID, forKey: "GID")
    row.setValue(nativeDouble(refs.amount), forKey: "amount")
    row.setValue(nativeDouble(refs.amount), forKey: "originalAmount")
    row.setValue(plan.currencyUnit, forKey: "originalCurrency")
    let trade = operation.kind == "investment_buy" || operation.kind == "investment_sell"
    row.setValue(trade ? 0.0 : 1.0, forKey: "originalExchangeRate")
    row.setValue(trade ? 0.0 : 1.0, forKey: "currencyExchangeRate")
    row.setValue(2, forKey: "status")
    row.setValue(0, forKey: "flags")
    row.setValue(true, forKey: "reconciled")
    row.setValue(operation.investmentSymbol, forKey: "investmentSymbol")
    row.setValue(try planTimestamp(operation.occurredAt!), forKey: "date")
    row.setValue(try planTimestamp(plan.createdAt), forKey: "objectCreationDate")
    row.setValue(operation.note, forKey: "notes")
    row.setValue(refs.account, forKey: "account")
    row.setValue(refs.payee, forKey: "payee")
    row.setValue(NSSet(array: refs.tags), forKey: "tags")
    if let holding = refs.holding {
        let fee = try decimalValue(operation.fee!, field: "W08 fee")
        row.setValue(holding, forKey: "investmentHolding")
        row.setValue(nativeDouble(try decimalValue(operation.quantity!, field: "W08 quantity")), forKey: "numberOfShares")
        row.setValue(nativeDouble(try decimalValue(operation.unitPrice!, field: "W08 price")), forKey: "pricePerShare")
        row.setValue(nativeDouble(fee), forKey: "fee")
        row.setValue(operation.holdingSymbol, forKey: "symbol")
    }
    for (index, category) in refs.categories.enumerated() {
        let assignment = NSEntityDescription.insertNewObject(forEntityName: "CategoryAssigment", into: context)
        assignment.setValue(nativeDouble(refs.amount), forKey: "amount")
        assignment.setValue(index, forKey: "assigmentNumber")
        assignment.setValue(category, forKey: "category")
        assignment.setValue(row, forKey: "transaction")
    }
    try requireStopped()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .beforeSave { _exit(86) }
#endif
    try context.save()
#if MONEYWIZ_TOOLS_TESTING
    if writerTestCrashPoint == .afterSave { _exit(87) }
#endif
    let readback = NSManagedObjectContext(concurrencyType: .privateQueueConcurrencyType)
    readback.persistentStoreCoordinator = context.persistentStoreCoordinator
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W08 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let receipt = try inspectInvestment(operation, plan: plan, context: readback, saved: true)
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
        if plan.capability.hasPrefix("write.create-") || plan.capability == "write.edit-transaction" ||
           plan.capability == "write.assign-payee-categories" ||
           plan.capability == "write.reconcile" || plan.capability == "write.unreconcile" ||
           plan.capability == "write.delete-adjust-balance-investment-total" ||
           plan.capability == "write.replace-import-with-transfer" ||
           ["write.investment-income", "write.investment-expense", "write.investment-buy",
            "write.investment-sell"].contains(plan.capability) {
            let fixtureName = plan.capability.hasPrefix("write.investment-") ? "W08" :
                (plan.capability == "write.replace-import-with-transfer" ? "W07" :
                (plan.capability == "write.delete-adjust-balance-investment-total" ? "W06" : "W01")
                )
            guard moneyWizApp.bundleIdentifier == "com.moneywiz.personalfinance",
                  installedVersion == "2026.37.1",
                  moneyWizApp.object(forInfoDictionaryKey: "CFBundleVersion") as? String == "449" else {
                throw HostError.message("\(fixtureName) disposable evidence is limited to TestFlight 2026.37.1 build 449")
            }
            let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
                ofType: NSSQLiteStoreType, at: arguments.store, options: nil)
            guard metadata["MoneyWizToolsDisposableFixture"] as? String == "W01-v1" else {
                throw HostError.message("\(fixtureName) live write remains blocked; marked disposable fixture required")
            }
        }
        if plan.capability == "write.adjust-balance-investment-total" {
            guard moneyWizApp.bundleIdentifier == "com.moneywiz.personalfinance",
                  installedVersion == "2026.37.1",
                  moneyWizApp.object(forInfoDictionaryKey: "CFBundleVersion") as? String == "449" else {
                throw HostError.message("W05 native reference is limited to TestFlight 2026.37.1 build 449")
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
