import AppKit
import CoreData
import CoreFoundation
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

// Match Python str.strip/str.isspace at every cross-language plan boundary.
let planWhitespace: CharacterSet = {
    var result = CharacterSet()
    for range in [9...13, 28...32, 0x85...0x85, 0xA0...0xA0, 0x1680...0x1680,
                  0x2000...0x200A, 0x2028...0x2029, 0x202F...0x202F,
                  0x205F...0x205F, 0x3000...0x3000] {
        for value in range { result.insert(charactersIn: String(UnicodeScalar(value)!)) }
    }
    return result
}()

func isBlank(_ value: String) -> Bool {
    value.trimmingCharacters(in: planWhitespace).isEmpty
}

func validatePlanScalarTypes(_ value: Any, key: String = "") throws {
    if let object = value as? [String: Any] {
        for (key, child) in object { try validatePlanScalarTypes(child, key: key) }
    } else if let array = value as? [Any] {
        for child in array { try validatePlanScalarTypes(child, key: key) }
    } else if let text = value as? String {
        let identities: Set<String> = ["plan_id", "owner_uri", "source_event_id",
            "store_uuid", "bundle_id", "version", "path", "model_path",
            "expected_account_gid", "account_gid", "operation_id", "transaction_gid",
            "recipient_transaction_gid", "transaction_numeric_id", "peer_transaction_gid",
            "peer_account_gid", "peer_currency_unit", "currency_unit", "payee_gid",
            "original_fee_currency",
            "original_transaction_gid", "target_payee_gid", "expected_old_payee_gid",
            "holding_gid", "holding_symbol", "investment_symbol", "gid", "object_uri",
            "source_evidence_refs", "tag_gids", "transaction_gids",
            "category_assignment_uris", "deletion_reason", "evidence_note", "entity", "transaction_entity", "symbol"]
        if identities.contains(key), isBlank(text) || text != text.trimmingCharacters(in: planWhitespace) {
            throw HostError.message("writer plan \(key) requires nonblank trimmed text")
        }
    } else if let number = value as? NSNumber {
        let integers: Set<String> = ["contract_version", "operation_schema_version", "asset_type", "currency_precision",
            "expected_native_status", "expected_native_flags", "source_count", "parsed_count",
            "status", "flags", "native_status", "native_flags", "user_id"]
        let booleans: Set<String> = ["expected_reconciled", "target_reconciled", "reconciled",
            "transaction_absent", "external_source_verified", "retained_verified"]
        let boolean = CFGetTypeID(number) == CFBooleanGetTypeID()
        if integers.contains(key), boolean || ["f", "d"].contains(String(cString: number.objCType)) {
            throw HostError.message("writer plan \(key) requires an exact JSON integer")
        }
        if booleans.contains(key), !boolean {
            throw HostError.message("writer plan \(key) requires an exact JSON boolean")
        }
    }
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
    let previousDestinationAccount: TransferDestinationAccount?
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
        case previousDestinationAccount = "previous_destination_account"
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
    let balanceMode: String?
    enum CodingKeys: String, CodingKey {
        case accountGID = "account_gid", currencyUnit = "currency_unit"
        case expectedCachedBalance = "expected_cached_balance"
        case balanceMode = "balance_mode"
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

struct TransferLegSnapshot: Decodable {
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
    let fee: String
    let originalFee: String
    let originalFeeCurrency: String?
    let originalAmount: String
    let peerAmount: String
    let peerCurrencyUnit: String
    let exchangeRate: String
    let peerTransactionGID: String
    let peerAccountGID: String
    let payeeGID: String?
    let tagGIDs: [String]
    let categoryAssignmentURIs: [String]

    enum CodingKeys: String, CodingKey {
        case transactionEntity = "transaction_entity", transactionGID = "transaction_gid"
        case transactionNumericID = "transaction_numeric_id", accountGID = "account_gid"
        case amount, currencyUnit = "currency_unit", occurredAt = "occurred_at"
        case status, flags, reconciled, note, description, fee
        case originalFee = "original_fee", originalFeeCurrency = "original_fee_currency"
        case originalAmount = "original_amount", peerAmount = "peer_amount"
        case peerCurrencyUnit = "peer_currency_unit", exchangeRate = "exchange_rate"
        case peerTransactionGID = "peer_transaction_gid", peerAccountGID = "peer_account_gid"
        case payeeGID = "payee_gid"
        case tagGIDs = "tag_gids", categoryAssignmentURIs = "category_assignment_uris"
    }
}

struct TransferPairSnapshot: Decodable {
    let sender: TransferLegSnapshot
    let recipient: TransferLegSnapshot
}

struct TransferRecipientEditDetails: Encodable {
    let recipientGID: String
    let recipientNumericID: String
    let recipientURI: String
    let reciprocalLinksVerified = true
    enum CodingKeys: String, CodingKey {
        case recipientGID = "recipient_gid", recipientNumericID = "recipient_numeric_id"
        case recipientURI = "recipient_uri", reciprocalLinksVerified = "reciprocal_links_verified"
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
    let description: String?
    let reportingExchangeRate: String?
    let currencyPrecision: Int?
    let expectedBalanceDelta: String?
    let changes: [String: EditScalar]?
    let expectedPrior: [String: EditScalar]?
    let expectedPair: TransferPairSnapshot?
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
    let deletionInventory: SupportedDeletionInventory?
    let recipientTransactionGID: String?
    let sourceOld: TransferOldRow?
    let destinationOld: TransferOldRow?
    let sendAt: String?
    let receiveAt: String?
    let senderAmount: String?
    let recipientAmount: String?
    let exchangeRate: String?
    let feeAmount: String?
    let holdingType: String?
    let holdingDescription: String?
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
        case description, reportingExchangeRate = "reporting_exchange_rate", currencyPrecision = "currency_precision"
        case expectedBalanceDelta = "expected_balance_delta"
        case changes
        case expectedPrior = "expected_prior"
        case expectedPair = "expected_pair"
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
        case deletionInventory = "deletion_inventory"
        case recipientTransactionGID = "recipient_transaction_gid"
        case sourceOld = "source_old"
        case destinationOld = "destination_old"
        case sendAt = "send_at", receiveAt = "receive_at"
        case senderAmount = "sender_amount", recipientAmount = "recipient_amount"
        case exchangeRate = "exchange_rate", feeAmount = "fee_amount"
        case holdingType = "holding_type", holdingDescription = "holding_description"
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
    var description: String? = nil
    var reportingExchangeRate: String? = nil
    var currencyPrecision: Int? = nil
    var holdingGID: String? = nil
    var holdingSymbol: String? = nil
    var assetType: Int? = nil
    var expectedPriorCash: String? = nil
    enum CodingKeys: String, CodingKey {
        case transactionEntity = "transaction_entity", transactionGID = "transaction_gid"
        case accountGID = "account_gid", ownerURI = "owner_uri", balanceUnit = "balance_unit"
        case expectedPriorBalance = "expected_prior_balance", targetBalance = "target_balance"
        case expectedBalanceDelta = "expected_balance_delta", currencyUnit = "currency_unit"
        case occurredAt = "occurred_at", timezone
        case description, reportingExchangeRate = "reporting_exchange_rate", currencyPrecision = "currency_precision"
        case holdingGID = "holding_gid", holdingSymbol = "holding_symbol"
        case assetType = "asset_type"
        case expectedPriorCash = "expected_prior_cash"
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

struct TransferRecipientEditPostcondition: Encodable {
    let senderGID: String
    let recipientGID: String
    let senderAccountGID: String
    let previousDestinationAccountGID: String
    let destinationAccountGID: String
    let recipientAmount: String
    let receiveAt: String
    enum CodingKeys: String, CodingKey {
        case senderGID = "sender_gid", recipientGID = "recipient_gid"
        case senderAccountGID = "sender_account_gid"
        case previousDestinationAccountGID = "previous_destination_account_gid"
        case destinationAccountGID = "destination_account_gid"
        case recipientAmount = "recipient_amount", receiveAt = "receive_at"
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
    var supportedDeletionPostcondition: SupportedDeletionPostcondition? = nil
    var transferPostcondition: TransferPostcondition? = nil
    var transferRecipientEditPostcondition: TransferRecipientEditPostcondition? = nil
    var transferRecipientEditDetails: TransferRecipientEditDetails? = nil
    var transferDetails: TransferDetails? = nil
    var investmentDetails: InvestmentDetails? = nil
    var holdingCreation: HoldingCreation? = nil

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
        case transferRecipientEditPostcondition = "transfer_recipient_edit_postcondition"
        case transferRecipientEditDetails = "transfer_recipient_edit_details"
        case investmentDetails = "investment_details"
        case holdingCreation = "holding_creation"
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
        try container.encodeIfPresent(transferRecipientEditPostcondition, forKey: .transferRecipientEditPostcondition)
        try container.encodeIfPresent(transferRecipientEditDetails, forKey: .transferRecipientEditDetails)
        try container.encodeIfPresent(investmentDetails, forKey: .investmentDetails)
        try container.encodeIfPresent(holdingCreation, forKey: .holdingCreation)
        if let supportedDeletionPostcondition { try container.encode(supportedDeletionPostcondition, forKey: .postcondition) }
        else if let transferPostcondition { try container.encode(transferPostcondition, forKey: .postcondition) }
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
    var description: String? = nil
    var reportingExchangeRate: String? = nil

    enum CodingKeys: String, CodingKey {
        case transactionEntity = "transaction_entity", transactionGID = "transaction_gid"
        case accountGID = "account_gid", ownerURI = "owner_uri", amount, currencyUnit = "currency_unit"
        case occurredAt = "occurred_at", timezone, payeeGID = "payee_gid", categorySplits = "category_splits"
        case tagGIDs = "tag_gids", note, refundReference = "refund_reference"
        case expectedBalanceDelta = "expected_balance_delta"
        case description, reportingExchangeRate = "reporting_exchange_rate"
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
        try c.encodeIfPresent(description, forKey: .description)
        try c.encodeIfPresent(reportingExchangeRate, forKey: .reportingExchangeRate)
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
    try validatePlanScalarTypes(rawPlan)
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
    let w10 = plan.capability == "write.reassign-transfer-recipient"
    if w10 {
        requiredKeys.insert("previous_destination_account")
        requiredKeys.insert("destination_account")
    }
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
        if kind == "adjust_investment_total" || extendedAdjustPolicies[kind ?? ""] != nil {
            try validateAdjustBalanceShape(rawOperation, plan: plan)
            continue
        }
        if kind == "delete_investment_total_adjustment" {
            try validateDeleteAdjustmentShape(rawOperation, plan: plan)
            continue
        }
        if kind == "delete_supported_transactions" {
            try validateSupportedDeletionShape(rawOperation, plan: plan)
            continue
        }
        if kind == "replace_import_with_transfer" {
            try validateTransferShape(rawOperation, plan: plan)
            continue
        }
        if kind == "reassign_transfer_recipient" {
            try validateTransferRecipientEditShape(rawOperation, plan: plan)
            continue
        }
        if kind == "create_income" || kind == "create_expense" || kind == "create_refund" ||
           ["investment_income", "investment_expense", "investment_buy", "investment_buy_new_holding", "investment_sell"].contains(kind) {
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
          (plan.capability == policy.capability || extendedAdjustPolicies.values.contains(where: { $0.capability == plan.capability }) || ["write.create-income", "write.create-expense", "write.create-refund", "write.edit-transaction", "write.assign-payee-categories", "write.reconcile", "write.unreconcile", "write.adjust-balance-investment-total", "write.delete-adjust-balance-investment-total", "write.delete-supported-transactions", "write.replace-import-with-transfer", "write.reassign-transfer-recipient", "write.investment-income", "write.investment-expense", "write.investment-buy", "write.investment-buy-new-holding", "write.investment-sell"].contains(plan.capability)),
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
              Set(rawDestination.keys) == Set(["account_gid", "currency_unit", "expected_cached_balance"])
                .union(destination.balanceMode == nil ? [] : ["balance_mode"]),
              destination.balanceMode == nil || destination.balanceMode == "ledger",
              !isBlank(destination.accountGID), destination.accountGID != plan.expectedAccountGID,
              destination.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
              plan.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil else {
            throw HostError.message("W07 destination account guard is invalid")
        }
        _ = try decimalValue(destination.expectedCachedBalance, field: "W07 destination balance")
    }
    if w10 {
        guard let destination = plan.destinationAccount,
              let previous = plan.previousDestinationAccount else {
            throw HostError.message("W10 current and target destination accounts are required")
        }
        for (name, account, rawKey) in [("current", previous, "previous_destination_account"), ("target", destination, "destination_account")] {
            guard let rawAccount = rawPlan[rawKey] as? [String: Any],
                  Set(rawAccount.keys) == Set(["account_gid", "currency_unit", "expected_cached_balance"])
                    .union(account.balanceMode == nil ? [] : ["balance_mode"]),
                  account.balanceMode == nil || account.balanceMode == "ledger",
                  !isBlank(account.accountGID),
                  account.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil else {
                throw HostError.message("W10 \(name) destination account guard is invalid")
            }
            _ = try decimalValue(account.expectedCachedBalance, field: "W10 \(name) destination balance")
        }
        guard plan.currencyUnit.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
              destination.currencyUnit == previous.currencyUnit,
              destination.accountGID != previous.accountGID,
              destination.accountGID != plan.expectedAccountGID else {
            throw HostError.message("W10 target account must be distinct and keep the recipient currency")
        }
        _ = try decimalValue(plan.expectedCachedAccountBalance, field: "W10 source balance")
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
    if extendedAdjustPolicies.values.contains(where: { $0.capability == plan.capability }) &&
       (plan.operations.count != 1 || extendedAdjustPolicies[plan.operations[0].kind]?.capability != plan.capability) {
        throw HostError.message("W05 requires exactly one matching adjustment operation")
    }
    if plan.capability == "write.delete-adjust-balance-investment-total" &&
       (plan.operations.count != 1 || plan.operations[0].kind != "delete_investment_total_adjustment") {
        throw HostError.message("W06 requires exactly one investment-total deletion")
    }
    if plan.capability == "write.delete-supported-transactions" &&
       (plan.operations.count != 1 || plan.operations[0].kind != "delete_supported_transactions") {
        throw HostError.message("W06 requires exactly one supported deletion closure")
    }
    if w07 && (plan.operations.count != 1 || plan.operations[0].kind != "replace_import_with_transfer") {
        throw HostError.message("W07 requires exactly one atomic transfer replacement")
    }
    if w10 && (plan.operations.count != 1 || plan.operations[0].kind != "reassign_transfer_recipient") {
        throw HostError.message("W10 requires exactly one linked-transfer recipient edit")
    }
    if ["write.investment-income", "write.investment-expense", "write.investment-buy", "write.investment-buy-new-holding", "write.investment-sell"].contains(plan.capability) &&
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
        if extendedAdjustPolicies[operation.kind] != nil || ["create_income", "create_expense", "create_refund", "adjust_investment_total",
            "investment_income", "investment_expense", "investment_buy", "investment_buy_new_holding", "investment_sell"].contains(operation.kind) {
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
        if operation.kind == "delete_supported_transactions" {
            guard operation.capability == plan.capability,
                  operation.ownerURI == plan.ownerURI,
                  operation.sourceEventID == plan.sourceEventID,
                  operationIDs.insert(operation.operationID).inserted,
                  transactionGIDs.insert(operation.transactionGID).inserted else {
                throw HostError.message("W06 supported deletion differs from its envelope")
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
        if operation.kind == "reassign_transfer_recipient" {
            guard operation.capability == plan.capability,
                  operation.ownerURI == plan.ownerURI,
                  operation.sourceEventID == plan.sourceEventID,
                  operation.transactionEntity == "TransferWithdrawTransaction",
                  operation.expectedPair?.sender.transactionGID == operation.transactionGID,
                  operation.expectedPair?.recipient.transactionGID == operation.recipientTransactionGID,
                  operationIDs.insert(operation.operationID).inserted,
                  transactionGIDs.insert(operation.transactionGID).inserted,
                  let recipientGID = operation.recipientTransactionGID,
                  transactionGIDs.insert(recipientGID).inserted else {
                throw HostError.message("W10 operation identities differ from its reviewed pair")
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

let extendedAdjustPolicies: [String: (capability: String, unit: String)] = [
    "adjust_account_balance": ("write.adjust-account-balance", "account_balance"),
    "adjust_investment_cash": ("write.adjust-investment-cash", "investment_cash"),
    "adjust_asset_quantity": ("write.adjust-asset-quantity", "asset_quantity"),
]

func validateAggregateCurrencyMetadata(_ raw: [String: Any]) throws -> Int {
    guard let precision = raw["currency_precision"] as? Int,
          [0, 2, 3, 6, 8].contains(precision),
          let rate = raw["reporting_exchange_rate"] as? String,
          let value = try? decimalValue(rate, field: "investment total reporting rate"),
          value >= 0, NSDecimalNumber(decimal: value).stringValue == rate else {
        throw HostError.message("investment total requires explicit currency precision and reporting rate")
    }
    return precision
}

// Account.currencyName stores fiat codes, legacy crypto codes, or the native
// code+coinMarketCapId identifier. Do not substitute ISO decimal conventions:
// MoneyWiz also lists six-decimal metals and eight-decimal crypto currencies.
func aggregateCurrencyPrecision(_ plan: WriterPlanV2) throws -> Int {
    guard let precision = plan.operations[0].currencyPrecision else {
        guard plan.currencyUnit == "GBP" else { throw HostError.message("investment total currency metadata is missing") }
        return 2 // Preserve the original GBP plan/digest/replay contract.
    }
    let resources = URL(fileURLWithPath: plan.appIdentity.path).appendingPathComponent("Contents/Resources")
    for (file, crypto) in [("currencies_fiat.plist", false), ("currencies_crypto_v2.plist", true)] {
        let data = try Data(contentsOf: resources.appendingPathComponent(file))
        guard let rows = try PropertyListSerialization.propertyList(from: data, format: nil) as? [[String: Any]] else {
            throw HostError.message("MoneyWiz currency catalog has an unsupported shape")
        }
        let matches = rows.filter { row in
            guard let code = row["currencyCode"] as? String else { return false }
            return code == plan.currencyUnit || (crypto && (row["coinMarketCapId"] as? String).map {
                code + "+" + $0 == plan.currencyUnit
            } == true)
        }
        if !matches.isEmpty {
            guard matches.allSatisfy({ row in
                guard let digits = row["numberOfDigits"] as? NSNumber,
                      CFGetTypeID(digits) != CFBooleanGetTypeID(),
                      !["f", "d"].contains(String(cString: digits.objCType)) else { return false }
                return digits.intValue == precision
            }) else { throw HostError.message("investment total precision differs from the MoneyWiz currency catalog") }
            return precision // Fiat identifiers take precedence over bare crypto symbols.
        }
    }
    throw HostError.message("investment total currency is absent from the reviewed MoneyWiz catalogs")
}

func validateAdjustBalanceShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let kind = raw["kind"] as? String ?? ""
    let policy = extendedAdjustPolicies[kind]
    let extended = policy != nil
    let units = kind == "adjust_asset_quantity"
    let currencyMetadata = !extended && (raw["currency_precision"] != nil || raw["reporting_exchange_rate"] != nil)
    var fields: Set<String> = ["transaction_entity", "transaction_gid", "account_gid", "owner_uri",
        "balance_unit", "expected_prior_balance", "target_balance", "expected_balance_delta",
        "currency_unit", "occurred_at", "timezone"]
    if extended { fields.formUnion(["description", "reporting_exchange_rate"]) }
    if currencyMetadata { fields.formUnion(["currency_precision", "reporting_exchange_rate"]) }
    if units { fields.formUnion(["holding_gid", "holding_symbol", "asset_type", "expected_prior_cash"]) }
    let required = fields.union(["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"])
    guard Set(raw.keys) == required,
          let post = raw["expected_postcondition"] as? [String: Any],
          Set(post.keys) == fields,
          NSDictionary(dictionary: post).isEqual(to: raw.filter { fields.contains($0.key) }),
          extended || kind == "adjust_investment_total",
          raw["capability"] as? String == (policy?.capability ?? "write.adjust-balance-investment-total"),
          plan.capability == (policy?.capability ?? "write.adjust-balance-investment-total"),
          raw["transaction_entity"] as? String == "ReconcileTransaction",
          raw["transaction_gid"] as? String == deterministicCreationGID(plan: plan),
          raw["account_gid"] as? String == plan.expectedAccountGID,
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          raw["balance_unit"] as? String == (policy?.unit ?? "investment_total"),
          raw["currency_unit"] as? String == plan.currencyUnit,
          raw["timezone"] as? String == plan.timezone,
          extended || plan.expectedCachedAccountBalance == "0",
          extended ? ["GBP", "EUR", "USD", "CAD"].contains(plan.currencyUnit) : (currencyMetadata || plan.currencyUnit == "GBP"),
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
    let precision = currencyMetadata ? try validateAggregateCurrencyMetadata(raw) : (units ? 8 : 2)
    guard amounts.allSatisfy({ value in
        var source = value
        var rounded = Decimal()
        NSDecimalRound(&rounded, &source, precision, .plain)
        return rounded == value
    }), amounts[1] - amounts[0] == amounts[2] else {
        throw HostError.message("W05 target minus prior differs from delta")
    }
    if extended {
        guard let description = raw["description"] as? String, !isBlank(description),
              description == description.trimmingCharacters(in: planWhitespace),
              let rate = raw["reporting_exchange_rate"] as? String,
              try decimalValue(rate, field: "W05 reporting rate") >= 0 else {
            throw HostError.message("W05 requires an explicit description and reporting rate")
        }
        if units {
            guard let gid = raw["holding_gid"] as? String, !isBlank(gid),
                  let symbol = raw["holding_symbol"] as? String, !isBlank(symbol),
                  let assetType = plan.operations[0].assetType, [0, 1].contains(assetType),
                  let cash = raw["expected_prior_cash"] as? String,
                  amounts[0] >= 0, amounts[1] >= 0, rate == "0" else {
                throw HostError.message("W05 asset identity, units or native zero reporting rate is invalid")
            }
            _ = try decimalValue(cash, field: "W05 prior cash")
        }
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
    var required: Set<String> = ["operation_id", "kind", "capability", "transaction_entity",
        "transaction_gid", "transaction_numeric_id", "account_gid", "owner_uri", "source_event_id",
        "balance_unit", "expected_amount", "expected_reconcile_amount", "expected_prior_balance",
        "target_balance", "expected_balance_delta", "currency_unit", "occurred_at", "timezone",
        "deletion_reason", "expected_postcondition"]
    let currencyMetadata = raw["currency_precision"] != nil || raw["reporting_exchange_rate"] != nil
    if currencyMetadata { required.formUnion(["currency_precision", "reporting_exchange_rate"]) }
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
          plan.expectedCachedAccountBalance == "0", currencyMetadata || plan.currencyUnit == "GBP",
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
    let precision = currencyMetadata ? try validateAggregateCurrencyMetadata(raw) : 2
    guard values[0] != 0, values[1] == values[2], values[3] == values[2] - values[0],
          values[4] == -values[0], values.allSatisfy({ value in
              var source = value
              var rounded = Decimal()
              NSDecimalRound(&rounded, &source, precision, .plain)
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
    let resulting = prior + (recipient == nil && destination.balanceMode != "ledger" ? received : 0)
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

func validateTransferRecipientEditShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "recipient_transaction_gid", "owner_uri", "source_event_id", "expected_pair",
        "expected_postcondition",
    ]
    guard Set(raw.keys) == required,
          raw["kind"] as? String == "reassign_transfer_recipient",
          raw["capability"] as? String == "write.reassign-transfer-recipient",
          raw["transaction_entity"] as? String == "TransferWithdrawTransaction",
          raw["owner_uri"] as? String == plan.ownerURI,
          raw["source_event_id"] as? String == plan.sourceEventID,
          let pair = raw["expected_pair"] as? [String: Any],
          Set(pair.keys) == ["sender", "recipient"],
          let sender = pair["sender"] as? [String: Any],
          let recipient = pair["recipient"] as? [String: Any] else {
        throw HostError.message("W10 operation contains unknown or missing fields")
    }
    let legKeys: Set<String> = [
        "transaction_entity", "transaction_gid", "transaction_numeric_id", "account_gid",
        "amount", "currency_unit", "occurred_at", "status", "flags", "reconciled",
        "note", "description", "fee", "original_fee", "original_fee_currency",
        "original_amount", "peer_amount", "peer_currency_unit", "exchange_rate",
        "peer_transaction_gid", "peer_account_gid", "payee_gid", "tag_gids", "category_assignment_uris",
    ]
    func validateLeg(_ row: [String: Any], entity: String, field: String) throws {
        guard Set(row.keys) == legKeys,
              row["transaction_entity"] as? String == entity,
              let gid = row["transaction_gid"] as? String, !isBlank(gid),
              gid == gid.trimmingCharacters(in: planWhitespace),
              let numericID = row["transaction_numeric_id"] as? String,
              let parsedID = Int(numericID), parsedID > 0, String(parsedID) == numericID,
              let accountGID = row["account_gid"] as? String, !isBlank(accountGID),
              accountGID == accountGID.trimmingCharacters(in: planWhitespace),
              let peerGID = row["peer_transaction_gid"] as? String, !isBlank(peerGID),
              peerGID == peerGID.trimmingCharacters(in: planWhitespace),
              let peerAccountGID = row["peer_account_gid"] as? String, !isBlank(peerAccountGID),
              peerAccountGID == peerAccountGID.trimmingCharacters(in: planWhitespace),
              row["amount"] is String,
              let currency = row["currency_unit"] as? String,
              currency.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
              let peerCurrency = row["peer_currency_unit"] as? String,
              peerCurrency.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
              let occurred = row["occurred_at"] as? String,
              let status = row["status"] as? Int, [1, 2].contains(status),
              let flags = row["flags"] as? Int, flags >= 0,
              row["reconciled"] is Bool,
              row["note"] is String || row["note"] is NSNull,
              row["description"] is String || row["description"] is NSNull,
              row["original_fee_currency"] is String || row["original_fee_currency"] is NSNull,
              row["payee_gid"] is String || row["payee_gid"] is NSNull,
              (row["note"] as? String).map({ $0 == $0.trimmingCharacters(in: planWhitespace) }) ?? true,
              (row["description"] as? String).map({ $0 == $0.trimmingCharacters(in: planWhitespace) }) ?? true,
              (row["original_fee_currency"] as? String).map({
                  $0 == $0.trimmingCharacters(in: planWhitespace)
                    && $0.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil
              }) ?? true,
              (row["payee_gid"] as? String).map({
                  !isBlank($0) && $0 == $0.trimmingCharacters(in: planWhitespace)
              }) ?? true,
              let tags = row["tag_gids"] as? [String], tags == Array(Set(tags)).sorted(),
              tags.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: planWhitespace) }),
              let categories = row["category_assignment_uris"] as? [String],
              categories == Array(Set(categories)).sorted(),
              categories.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: planWhitespace) }) else {
            throw HostError.message("W10 \(field) snapshot contains invalid identity or scalar types")
        }
        let decimalFields = ["amount", "fee", "original_fee", "original_amount", "peer_amount", "exchange_rate"]
        for name in decimalFields {
            guard let value = row[name] as? String else {
                throw HostError.message("W10 \(field).\(name) must be canonical decimal text")
            }
            let decimal = try decimalValue(value, field: "W10 \(field).\(name)")
            guard NSDecimalNumber(decimal: decimal).stringValue == value else {
                throw HostError.message("W10 \(field).\(name) must be canonical decimal text")
            }
        }
        _ = try precisePlanTimestamp(occurred)
    }
    try validateLeg(sender, entity: "TransferWithdrawTransaction", field: "sender")
    try validateLeg(recipient, entity: "TransferDepositTransaction", field: "recipient")
    guard let previous = plan.previousDestinationAccount,
          let target = plan.destinationAccount,
          let senderGID = sender["transaction_gid"] as? String,
          let recipientGID = recipient["transaction_gid"] as? String,
          let senderAmountText = sender["amount"] as? String,
          let recipientAmountText = recipient["amount"] as? String,
          let senderPeerAmountText = sender["peer_amount"] as? String,
          let recipientPeerAmountText = recipient["peer_amount"] as? String,
          let senderRate = sender["exchange_rate"] as? String,
          let recipientRate = recipient["exchange_rate"] as? String,
          (raw["transaction_gid"] as? String) == senderGID,
          (raw["recipient_transaction_gid"] as? String) == recipientGID,
          (sender["peer_transaction_gid"] as? String) == recipientGID,
          (recipient["peer_transaction_gid"] as? String) == senderGID,
          (sender["account_gid"] as? String) == plan.expectedAccountGID,
          (recipient["account_gid"] as? String) == previous.accountGID,
          (sender["peer_account_gid"] as? String) == previous.accountGID,
          (recipient["peer_account_gid"] as? String) == plan.expectedAccountGID,
          (sender["currency_unit"] as? String) == plan.currencyUnit,
          (recipient["currency_unit"] as? String) == previous.currencyUnit,
          (sender["peer_currency_unit"] as? String) == previous.currencyUnit,
          (recipient["peer_currency_unit"] as? String) == plan.currencyUnit,
          target.currencyUnit == previous.currencyUnit,
          target.accountGID != previous.accountGID,
          target.accountGID != plan.expectedAccountGID,
          try decimalValue(senderAmountText, field: "W10 sender amount") < 0,
          try decimalValue(recipientAmountText, field: "W10 recipient amount") > 0,
          try decimalValue(senderPeerAmountText, field: "W10 sender peer amount") == decimalValue(recipientAmountText, field: "W10 recipient amount"),
          try decimalValue(recipientPeerAmountText, field: "W10 recipient peer amount") == decimalValue(senderAmountText, field: "W10 sender amount"),
          senderRate == recipientRate else {
        throw HostError.message("W10 transfer pair or account identities are not reciprocal")
    }
    let expectedPostcondition: [String: Any] = [
        "sender_gid": senderGID,
        "recipient_gid": recipientGID,
        "sender_account_gid": plan.expectedAccountGID,
        "previous_destination_account_gid": previous.accountGID,
        "destination_account_gid": target.accountGID,
        "recipient_amount": recipientAmountText,
        "receive_at": recipient["occurred_at"] as? String ?? "",
    ]
    guard let postcondition = raw["expected_postcondition"] as? [String: Any],
          postcondition as NSDictionary == expectedPostcondition as NSDictionary else {
        throw HostError.message("W10 postcondition differs from the reviewed transfer pair")
    }
}

func validateCreationOperationShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let investmentKinds: Set<String> = ["investment_income", "investment_expense", "investment_buy", "investment_buy_new_holding", "investment_sell"]
    let investment = investmentKinds.contains(raw["kind"] as? String ?? "")
    var extra: Set<String> = ["account_mode", "cash_event_type", "investment_symbol", "holding_gid", "holding_symbol",
        "asset_type", "quantity", "unit_price", "fee", "fee_currency",
        "expected_prior_cash", "expected_final_cash", "expected_prior_units", "expected_final_units"]
    let base: Set<String> = [
        "operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "account_gid", "owner_uri", "source_event_id", "amount", "currency_unit",
        "occurred_at", "timezone", "payee_gid", "category_splits", "tag_gids", "note",
        "refund_reference", "expected_balance_delta", "expected_postcondition",
    ]
    let optional = Set(raw.keys).intersection(investment ? ["description"] : ["description", "reporting_exchange_rate"])
    if raw["kind"] as? String == "investment_buy_new_holding" { extra.formUnion(["holding_type", "holding_description"]) }
    let creationBase = base.union(optional)
    let required = investment ? creationBase.union(extra) : creationBase
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
          Set(postcondition.keys) == creationBase.subtracting(["operation_id", "kind", "capability", "source_event_id", "expected_postcondition"]),
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
        guard let value = raw[field] as? String, !isBlank(value), value == value.trimmingCharacters(in: planWhitespace) else {
            throw HostError.message("W01 identity text must be trimmed and nonblank")
        }
    }
    for field in ["payee_gid", "note", "description"] {
        if let value = raw[field] as? String, isBlank(value) || value != value.trimmingCharacters(in: planWhitespace) {
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
    if optional.contains("description"), !(raw["description"] is String) {
        throw HostError.message("W01 description must be a nonblank string")
    }
    if optional.contains("reporting_exchange_rate") {
        guard let rate = raw["reporting_exchange_rate"] as? String,
              try canonicalDecimal(rate) > 0 else {
            throw HostError.message("W01 reporting exchange rate must be positive canonical Decimal text")
        }
    }
    let mappings = [
        "create_income": ("write.create-income", "DepositTransaction", 1),
        "create_expense": ("write.create-expense", "WithdrawTransaction", -1),
        "create_refund": ("write.create-refund", "RefundTransaction", 1),
        "investment_income": ("write.investment-income", "DepositTransaction", 1),
        "investment_expense": ("write.investment-expense", "WithdrawTransaction", -1),
        "investment_buy": ("write.investment-buy", "InvestmentBuyTransaction", -1),
        "investment_buy_new_holding": ("write.investment-buy-new-holding", "InvestmentBuyTransaction", -1),
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
        guard value * parsedAmount > 0, gid == gid.trimmingCharacters(in: planWhitespace) else {
            throw HostError.message("W01 category split sign or identity is invalid")
        }
        total += value
    }
    let transactionAmount = try decimalValue(amount, field: "creation amount")
    if !splits.isEmpty && total != transactionAmount {
        throw HostError.message("writer v2 category split total does not equal transaction amount")
    }
    guard Set(tags).count == tags.count, tags == tags.sorted(),
          tags.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: planWhitespace) }),
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
        let trade = kind == "investment_buy" || kind == "investment_buy_new_holding" || kind == "investment_sell"
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
                  finalUnits == units + (kind != "investment_sell" ? quantity : -quantity),
                  parsedAmount == (kind != "investment_sell" ? -(quantity * price + fee) : quantity * price - fee) else {
                throw HostError.message("W08 trade amount, asset, or units is invalid")
            }
            if kind == "investment_buy_new_holding" {
                var sourceQuantity = quantity, roundedQuantity = Decimal()
                NSDecimalRound(&roundedQuantity, &sourceQuantity, 8, .plain)
                guard operation.assetType == 0, unitsText == "0",
                      quantity == roundedQuantity,
                      let holdingType = raw["holding_type"] as? String, nativeHoldingTypes.contains(holdingType),
                      let description = raw["holding_description"] as? String, !isBlank(description),
                      description == description.trimmingCharacters(in: planWhitespace),
                      gid == "\(plan.expectedAccountGID)-\(symbol)-0",
                      symbol == symbol.trimmingCharacters(in: planWhitespace) else {
                    throw HostError.message("W08 first Buy holding type, description, identity or prior units is invalid")
                }
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
               isBlank(symbol) || symbol != symbol.trimmingCharacters(in: planWhitespace) {
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
          scope.transactionGIDs.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: planWhitespace) }),
          !isBlank(scope.verifiedBalance) else {
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
          let status = raw["expected_native_status"] as? Int, [1, 2].contains(status),
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
              value == value.trimmingCharacters(in: planWhitespace) else {
            throw HostError.message("W04 identity text must be trimmed and nonblank")
        }
    }
    if reconcile {
        guard raw["correction_reason"] is NSNull else {
            throw HostError.message("W04 reconcile does not accept a correction reason")
        }
    } else {
        guard let reason = raw["correction_reason"] as? String,
              !isBlank(reason), reason == reason.trimmingCharacters(in: planWhitespace) else {
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
              value == value.trimmingCharacters(in: planWhitespace) else {
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
           isBlank(gid) || gid != gid.trimmingCharacters(in: planWhitespace) {
            throw HostError.message("W03 payee GID is invalid")
        }
        var total = Decimal.zero, ids: [String] = []
        for split in splits {
            guard Set(split.keys) == ["category_gid", "amount"],
                  let gid = split["category_gid"] as? String, !isBlank(gid),
                  gid == gid.trimmingCharacters(in: planWhitespace),
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
        guard let s = raw[key] as? String, !isBlank(s), s == s.trimmingCharacters(in: planWhitespace) else {
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
                if let s = v as? String, isBlank(s) || s != s.trimmingCharacters(in: planWhitespace) {
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
                                currency: String, allowReconciled: Bool = false) throws {
    guard ["DepositTransaction", "WithdrawTransaction", "RefundTransaction"].contains(transaction.entity.name ?? ""),
          (transaction.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
          transaction.value(forKey: "originalCurrency") as? String == currency,
          (allowReconciled || (transaction.value(forKey: "reconciled") as? NSNumber)?.boolValue == false),
          [1, 2].contains((transaction.value(forKey: "status") as? NSNumber)?.intValue ?? -1),
          (transaction.value(forKey: "flags") as? NSNumber)?.intValue == 0,
          (transaction.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
          transaction.value(forKey: "investmentHolding") == nil,
          transaction.value(forKey: "autoSkipLinkedScheduledTransactionGID") == nil ||
            transaction.value(forKey: "autoSkipLinkedScheduledTransactionGID") as? String == "",
          transaction.value(forKey: "investmentSymbol") == nil,
          transaction.value(forKey: "symbol") == nil,
          transaction.value(forKey: "originalFeeCurrency") == nil,
          try nativeDecimal(transaction, "originalExchangeRate") == 1 else {
        throw HostError.message("W02 requires an ordinary unreconciled same-account same-currency transaction")
    }
    for key in ["fee", "originalFee", "numberOfShares", "pricePerShare"] {
        guard try nativeDecimal(transaction, key) == 0 else { throw HostError.message("W02 unsupported investment, fee, or FX state") }
    }
    guard try nativeDecimal(transaction, "currencyExchangeRate") >= 0 else {
        throw HostError.message("ordinary transaction has an invalid reporting exchange rate")
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
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let account = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                      currency: plan.currencyUnit, context: context)
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
    let after = before + (usesFixtureBalanceCache(context) ? delta : 0)
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
    if usesFixtureBalanceCache(context), allowed[prior.account.objectID] != nil {
        prior.account.setValue(nativeDouble(prior.balanceAfter), forKey: "ballance")
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
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let account = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                      currency: plan.currencyUnit, context: context)
    try validateAccountGuards(account, plan: plan)
    let scopeBalance = usesFixtureBalanceCache(context)
        ? try nativeDecimal(account, "ballance") : try investmentLedger(account)
    guard scopeBalance == (try decimalValue(scope.verifiedBalance, field: "W04 verified balance")) else {
        throw HostError.message("W04 account balance differs from reviewed scope")
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
        for key in ["fee", "originalFee", "numberOfShares", "pricePerShare"] {
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
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let account = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                      currency: plan.currencyUnit, context: context)
    let owner = account.value(forKey: "user") as! NSManagedObject
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

// Aggregate portfolios may contain cash income, fees and funding alongside
// valuation adjustments. Validate those existing native rows without changing them.
func aggregateActivityAmount(_ row: NSManagedObject, account: NSManagedObject) throws -> Decimal {
    let currency = account.value(forKey: "currencyName") as! String
    if ["DepositTransaction", "WithdrawTransaction", "RefundTransaction"].contains(row.entity.name ?? "") {
        try validateOrdinaryEditTarget(row, account: account, currency: currency, allowReconciled: true)
    } else {
        guard ["TransferDepositTransaction", "TransferWithdrawTransaction"].contains(row.entity.name ?? ""),
              (row.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              row.value(forKey: "originalCurrency") as? String == currency,
              try nativeDecimal(row, "originalAmount") == nativeDecimal(row, "amount"),
              try nativeDecimal(row, "originalExchangeRate") == 1,
              (row.value(forKey: "status") as? NSNumber)?.intValue == 2,
              (row.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              row.value(forKey: "investmentHolding") == nil,
              try nativeDecimal(row, "numberOfShares") == 0,
              try nativeDecimal(row, "fee") == 0,
              try nativeDecimal(row, "originalFee") == 0 else {
            throw HostError.message("aggregate account history contains unsupported cash activity")
        }
        let incoming = row.entity.name == "TransferDepositTransaction"
        let peerKey = incoming ? "senderTransaction" : "recipientTransaction"
        let accountKey = incoming ? "senderAccount" : "recipientAccount"
        let inverseKey = incoming ? "recipientTransaction" : "senderTransaction"
        guard let peer = row.value(forKey: peerKey) as? NSManagedObject,
              let peerAccount = row.value(forKey: accountKey) as? NSManagedObject,
              (peer.value(forKey: inverseKey) as? NSManagedObject)?.objectID == row.objectID,
              (peer.value(forKey: "account") as? NSManagedObject)?.objectID == peerAccount.objectID,
              (peerAccount.value(forKey: "user") as? NSManagedObject)?.objectID ==
                  (account.value(forKey: "user") as? NSManagedObject)?.objectID else {
            throw HostError.message("aggregate account has an incomplete funding transfer")
        }
    }
    return try nativeDecimal(row, "amount")
}

struct AdjustBalanceInspection {
    let receipt: WriterResultV2
    let account: NSManagedObject
    let openingBalance: Decimal
}

func adjustBalancePostcondition(_ operation: WriterOperationV2) -> AdjustBalancePostcondition {
    var result = AdjustBalancePostcondition(transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID, accountGID: operation.accountGID!,
        ownerURI: operation.ownerURI, balanceUnit: operation.balanceUnit!,
        expectedPriorBalance: operation.expectedPriorBalance!, targetBalance: operation.targetBalance!,
        expectedBalanceDelta: operation.expectedBalanceDelta!, currencyUnit: operation.currencyUnit!,
        occurredAt: operation.occurredAt!, timezone: operation.timezone!)
    result.currencyPrecision = operation.currencyPrecision
    if operation.currencyPrecision != nil { result.reportingExchangeRate = operation.reportingExchangeRate }
    if extendedAdjustPolicies[operation.kind] != nil {
        result.description = operation.description
        result.reportingExchangeRate = operation.reportingExchangeRate
        result.holdingGID = operation.holdingGID
        result.holdingSymbol = operation.holdingSymbol
        result.assetType = operation.assetType
        result.expectedPriorCash = operation.expectedPriorCash
    }
    return result
}

func inspectAdjustBalance(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                          saved: Bool = false) throws -> AdjustBalanceInspection {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W05 missing coordinator") }
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let operation = plan.operations[0]
    let precision = try aggregateCurrencyPrecision(plan)
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
    let adjustmentOnly = transactions.allSatisfy { $0.entity.name == "ReconcileTransaction" }
    var sum: Decimal = 0
    var latest = Date.distantPast
    let ordered = transactions.sorted {
        ($0.value(forKey: "date") as? Date ?? .distantPast) <
            ($1.value(forKey: "date") as? Date ?? .distantPast)
    }
    for transaction in ordered {
        if transaction.entity.name != "ReconcileTransaction" {
            guard let date = transaction.value(forKey: "date") as? Date else {
                throw HostError.message("W05 account activity lacks a date")
            }
            sum += try aggregateActivityAmount(transaction, account: account)
            latest = max(latest, date)
            continue
        }
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
        NSDecimalRound(&roundedRowBalance, &rowBalance, precision, .plain)
        // Native cash entries can be backdated after an adjustment. Its stored
        // target is then a historical annotation, not the current running sum.
        let historicalTarget = try nativeDecimal(transaction, "reconcileAmount")
        guard !adjustmentOnly || historicalTarget == roundedRowBalance else {
            throw HostError.message("W05 account history has an inconsistent adjustment balance")
        }
        guard date > latest else {
            throw HostError.message("W05 account history has ambiguous adjustment dates")
        }
        latest = date
    }
    var unrounded = opening + sum
    var actual = Decimal()
    NSDecimalRound(&actual, &unrounded, precision, .plain)
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
              try nativeDecimal(existing, "currencyExchangeRate") == decimalValue(operation.reportingExchangeRate ?? "0", field: "W05 reporting rate"),
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

func roundedBalance(_ value: Decimal, scale: Int) -> Decimal {
    var source = value
    var rounded = Decimal()
    NSDecimalRound(&rounded, &source, scale, .plain)
    return rounded
}

// Native Forex holdings use signed quantities on deposits/adjustments and
// separate signed from/to quantities on exchange rows. Stock trades use the
// existing W08 Buy/Sell path. A quantity adjustment carries no cash movement.
func forexUnits(_ holding: NSManagedObject, account: NSManagedObject,
                excluding: Set<NSManagedObjectID> = []) throws -> Decimal {
    var total = try nativeDecimal(holding, "openningNumberOfShares")
    for row in try relatedObjects(account, "transactionsHistory") {
        if excluding.contains(row.objectID) { continue }
        let direct = (row.value(forKey: "investmentHolding") as? NSManagedObject)?.objectID == holding.objectID
        let exchange = row.entity.name == "InvestmentExchangeTransaction"
        let from = exchange && (row.value(forKey: "fromInvestmentHolding") as? NSManagedObject)?.objectID == holding.objectID
        let to = exchange && (row.value(forKey: "toInvestmentHolding") as? NSManagedObject)?.objectID == holding.objectID
        if !direct && !from && !to { continue }
        guard (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0 else {
            throw HostError.message("W05 holding history contains a void row")
        }
        if direct {
            guard ["DepositTransaction", "ReconcileTransaction", "InvestmentBuyTransaction", "InvestmentSellTransaction"].contains(row.entity.name ?? ""),
                  row.value(forKey: "symbol") as? String == holding.value(forKey: "symbol") as? String else {
                throw HostError.message("W05 Forex holding history contains an unsupported transaction")
            }
            let quantity = try nativeDecimal(row, "numberOfShares")
            if row.entity.name == "InvestmentBuyTransaction" || row.entity.name == "InvestmentSellTransaction" {
                guard quantity > 0 else { throw HostError.message("W05 trade has nonpositive units") }
            }
            total += row.entity.name == "InvestmentSellTransaction" ? -quantity : quantity
        } else {
            // Currency-denominated exchange fees modify the corresponding leg.
            let fee = try nativeDecimal(row, "originalFee")
            if from {
                let units = try nativeDecimal(row, "fromNumberOfShares")
                guard units <= 0 else { throw HostError.message("W05 invalid outgoing exchange quantity") }
                total += units
                if row.value(forKey: "originalFeeCurrency") as? String == holding.value(forKey: "symbol") as? String {
                    total += fee
                }
            }
            if to {
                let units = try nativeDecimal(row, "toNumberOfShares")
                guard units >= 0 else { throw HostError.message("W05 invalid incoming exchange quantity") }
                total += units
                if row.value(forKey: "originalFeeCurrency") as? String == holding.value(forKey: "symbol") as? String {
                    total += fee
                }
            }
        }
    }
    let units = roundedBalance(total, scale: 8)
    guard units >= 0 else { throw HostError.message("W05 negative derived asset quantity") }
    return units
}

struct ExtendedAdjustmentInspection {
    let receipt: WriterResultV2
    let account: NSManagedObject
    let holding: NSManagedObject?
}

func inspectExtendedAdjustment(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                               saved: Bool = false) throws -> ExtendedAdjustmentInspection {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W05 missing coordinator") }
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let operation = plan.operations[0]
    let account = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                      currency: plan.currencyUnit, context: context)
    guard try nativeDecimal(account, "ballance") == decimalValue(plan.expectedCachedAccountBalance, field: "W05 cache") else {
        throw HostError.message("W05 account cache changed")
    }
    let units = operation.kind == "adjust_asset_quantity"
    let holding: NSManagedObject?
    if units {
        guard ["InvestmentAccount", "ForexAccount"].contains(account.entity.name ?? "") else {
            throw HostError.message("W05 quantity adjustment requires an investment or Forex account")
        }
        let object = try fetchExactObject(entityName: "InvestmentHolding", gid: operation.holdingGID!, context: context)
        guard (object.value(forKey: "investmentAccount") as? NSManagedObject)?.objectID == account.objectID,
              object.value(forKey: "symbol") as? String == operation.holdingSymbol,
              (object.value(forKey: "investmentObjectType") as? NSNumber)?.intValue == operation.assetType,
              operation.assetType == (account.entity.name == "ForexAccount" ? 1 : 0),
              try relatedObjects(account, "investmentHoldings").contains(object) else {
            throw HostError.message("W05 holding identity or native quantity mode differs")
        }
        holding = object
    } else {
        let investment = account.entity.name == "InvestmentAccount"
        guard operation.kind == "adjust_investment_cash" ? investment :
            !["InvestmentAccount", "ForexAccount"].contains(account.entity.name ?? "") else {
            throw HostError.message("W05 balance unit differs from native account type")
        }
        holding = nil
    }
    let cash = try investmentLedger(account)
    let actual = try holding.map { try investmentUnits($0, account: account) } ?? cash
    if units {
        guard cash == (try decimalValue(operation.expectedPriorCash!, field: "W05 unchanged cash")) else {
            throw HostError.message("W05 quantity adjustment cash precondition changed")
        }
    }
    let prior = try decimalValue(operation.expectedPriorBalance!, field: "W05 prior")
    let target = try decimalValue(operation.targetBalance!, field: "W05 target")
    let occurred = try planTimestamp(operation.occurredAt!)
    let candidates = try creationObjects(entity: "SyncObject", gid: operation.transactionGID, context: context)
    guard candidates.count <= 1 else { throw HostError.message("W05 adjustment GID collision") }
    let existing = candidates.first
    if let row = existing {
        guard row.entity.name == "ReconcileTransaction",
              (row.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              (row.value(forKey: "investmentHolding") as? NSManagedObject)?.objectID == holding?.objectID,
              row.value(forKey: "date") as? Date == occurred,
              row.value(forKey: "objectCreationDate") as? Date == (try planTimestamp(plan.createdAt)),
              row.value(forKey: "desc") as? String == operation.description,
              row.value(forKey: "notes") as? String == "",
              row.value(forKey: "symbol") as? String == operation.holdingSymbol,
              (row.value(forKey: "status") as? NSNumber)?.intValue == 2,
              (row.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              (row.value(forKey: "reconciled") as? NSNumber)?.boolValue == false,
              (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              try nativeDecimal(row, "amount") == (units ? 0 : target - prior),
              try nativeDecimal(row, "reconcileAmount") == (units ? 0 : target),
              try nativeDecimal(row, "numberOfShares") == (units ? target - prior : 0),
              try nativeDecimal(row, "reconcileNumberOfShares") == (units ? target : 0),
              try nativeDecimal(row, "currencyExchangeRate") == decimalValue(operation.reportingExchangeRate!, field: "W05 rate") else {
            throw HostError.message("W05 existing GID differs from the reviewed adjustment")
        }
        for key in ["originalAmount", "originalExchangeRate", "originalFee", "fee", "pricePerShare"] {
            guard try nativeDecimal(row, key) == 0 else { throw HostError.message("W05 unsupported adjustment scalar") }
        }
        for key in ["originalCurrency", "originalFeeCurrency", "investmentSymbol"] {
            guard row.value(forKey: key) == nil else { throw HostError.message("W05 unsupported adjustment metadata") }
        }
        for (key, relationship) in row.entity.relationshipsByName where !["account", "investmentHolding"].contains(key) {
            let empty = relationship.isToMany ? try relatedObjects(row, key).isEmpty : row.value(forKey: key) == nil
            guard empty else { throw HostError.message("W05 adjustment has unexpected relationships") }
        }
    }
    let latest = try relatedObjects(account, "transactionsHistory").compactMap { $0.value(forKey: "date") as? Date }.max() ?? .distantPast
    let classification: String
    if existing != nil && actual == target { classification = saved ? "applied" : "noop" }
    else if existing == nil && actual == target && prior == target { classification = "noop" }
    else if existing == nil && actual == prior && occurred > latest { classification = "retry_safe" }
    else { classification = "unknown" }
    let success = classification == "applied" || classification == "noop"
    var item = WriterOperationResultV2(operationID: operation.operationID,
        status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID, durableURI: existing?.objectID.uriRepresentation().absoluteString,
        durableNumericID: existing.map { durableNumericID($0.objectID) }, oldPayeeGID: nil, newPayeeGID: nil, postcondition: nil)
    if success { item.adjustBalancePostcondition = adjustBalancePostcondition(operation) }
    return ExtendedAdjustmentInspection(receipt: WriterResultV2(contractVersion: 2, planID: plan.planID,
        planDigest: plan.planDigest, classification: classification, verified: success, operations: [item]),
        account: account, holding: holding)
}

func extendedAdjustmentV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                          requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let before = try inspectExtendedAdjustment(plan, context: context)
    if before.receipt.classification == "noop" { return before.receipt }
    guard before.receipt.classification == "retry_safe" else { throw HostError.message("W05 prior balance, date or GID is stale") }
    let history = try relatedObjects(before.account, "transactionsHistory")
    let existing = [before.account] + Array(history) + (before.holding.map { [$0] } ?? [])
    let preimages = try existing.map { object -> CreationPreimage in
        let allowed: Set<String> = object.objectID == before.account.objectID ? ["relationship:transactionsHistory"] :
            object.objectID == before.holding?.objectID ? ["relationship:investmentTransactions"] : []
        var fingerprint = try immutableTransactionFingerprint(object)
        if object.entity.relationshipsByName["payee"] != nil {
            fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
        }
        return CreationPreimage(objectID: object.objectID,
            fingerprint: fingerprint.filter { !allowed.contains($0.key) }, allowedKeys: allowed)
    }
    let operation = plan.operations[0]
    let units = before.holding != nil
    let delta = try decimalValue(operation.expectedBalanceDelta!, field: "W05 delta")
    let target = try decimalValue(operation.targetBalance!, field: "W05 target")
    let row = NSEntityDescription.insertNewObject(forEntityName: "ReconcileTransaction", into: context)
    row.setValue(operation.transactionGID, forKey: "GID")
    row.setValue(nativeDouble(units ? 0 : delta), forKey: "amount")
    row.setValue(nativeDouble(units ? 0 : target), forKey: "reconcileAmount")
    row.setValue(nativeDouble(units ? delta : 0), forKey: "numberOfShares")
    row.setValue(nativeDouble(units ? target : 0), forKey: "reconcileNumberOfShares")
    row.setValue(nativeDouble(try decimalValue(operation.reportingExchangeRate!, field: "W05 reporting rate")), forKey: "currencyExchangeRate")
    row.setValue(try planTimestamp(operation.occurredAt!), forKey: "date")
    row.setValue(try planTimestamp(plan.createdAt), forKey: "objectCreationDate")
    row.setValue(operation.description, forKey: "desc")
    row.setValue("", forKey: "notes")
    row.setValue(2, forKey: "status")
    row.setValue(before.account, forKey: "account")
    row.setValue(before.holding, forKey: "investmentHolding")
    row.setValue(operation.holdingSymbol, forKey: "symbol")
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
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W05 independent read-back did not run"))
    readback.performAndWait {
        result = Result {
            let verified = try inspectExtendedAdjustment(plan, context: readback, saved: true)
            guard verified.receipt.classification == "applied" else { throw HostError.message("W05 independent read-back differs") }
            try verifyCreationPreimages(preimages, context: readback)
            return verified.receipt
        }
    }
    return try result.get()
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
    transaction.setValue(nativeDouble(try decimalValue(operation.reportingExchangeRate ?? "0", field: "W05 reporting rate")), forKey: "currencyExchangeRate")
    transaction.setValue("New balance", forKey: "desc")
    transaction.setValue("", forKey: "notes")
    transaction.setValue(2, forKey: "status")
    transaction.setValue(before.account, forKey: "account")
    if transaction.entity.relationshipsByName["user"] != nil {
        transaction.setValue(before.account.value(forKey: "user"), forKey: "user")
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
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let operation = plan.operations[0]
    let precision = try aggregateCurrencyPrecision(plan)
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
        throw HostError.message("W06 account identity or aggregate investment shape differs")
    }
    let opening = try nativeDecimal(account, "openingBalance")
    let history = try relatedObjects(account, "transactionsHistory").sorted {
        ($0.value(forKey: "date") as? Date ?? .distantPast) <
            ($1.value(forKey: "date") as? Date ?? .distantPast)
    }
    let adjustmentOnly = history.allSatisfy { $0.entity.name == "ReconcileTransaction" }
    var total = opening
    var latest = Date.distantPast
    for transaction in history {
        if transaction.entity.name != "ReconcileTransaction" {
            guard let date = transaction.value(forKey: "date") as? Date else {
                throw HostError.message("W06 account activity lacks a date")
            }
            total += try aggregateActivityAmount(transaction, account: account)
            latest = max(latest, date)
            continue
        }
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
        NSDecimalRound(&rounded, &source, precision, .plain)
        let historicalTarget = try nativeDecimal(transaction, "reconcileAmount")
        guard !adjustmentOnly || historicalTarget == rounded else {
            throw HostError.message("W06 account history has an inconsistent adjustment balance")
        }
        latest = date
    }
    var source = total
    var actual = Decimal()
    NSDecimalRound(&actual, &source, precision, .plain)
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
              try nativeDecimal(target, "currencyExchangeRate") == decimalValue(operation.reportingExchangeRate ?? "0", field: "W06 reporting rate") else {
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
    try requireReviewedRuntime(plan, coordinator: coordinator)
    guard (destination.balanceMode == "ledger") == !usesFixtureBalanceCache(context) else {
        throw HostError.message("W07 destination balance mode differs from native store semantics")
    }
    let sender = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                     currency: plan.currencyUnit, context: context)
    let recipient = try reviewedAccount(destination.accountGID, ownerURI: plan.ownerURI,
                                        currency: destination.currencyUnit, context: context)
    guard sender.objectID != recipient.objectID else {
        throw HostError.message("W07 transfer accounts must differ")
    }
    return (sender, recipient)
}

struct TransferRecipientEditInspection {
    let receipt: WriterResultV2
    let senderAccount: NSManagedObject
    let previousDestinationAccount: NSManagedObject
    let destinationAccount: NSManagedObject
    let sender: NSManagedObject
    let recipient: NSManagedObject
    let alreadyReassigned: Bool
}

func transferRecipientEditAccounts(_ plan: WriterPlanV2, context: NSManagedObjectContext)
    throws -> (NSManagedObject, NSManagedObject, NSManagedObject) {
    guard let coordinator = context.persistentStoreCoordinator,
          let previous = plan.previousDestinationAccount,
          let destination = plan.destinationAccount else {
        throw HostError.message("W10 current and target destination accounts are required")
    }
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let fixtureCache = usesFixtureBalanceCache(context)
    guard (previous.balanceMode == "ledger") == !fixtureCache,
          (destination.balanceMode == "ledger") == !fixtureCache else {
        throw HostError.message("W10 destination balance modes differ from native store semantics")
    }
    let sender = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                     currency: plan.currencyUnit, context: context)
    let oldDestination = try reviewedAccount(previous.accountGID, ownerURI: plan.ownerURI,
                                              currency: previous.currencyUnit, context: context)
    let newDestination = try reviewedAccount(destination.accountGID, ownerURI: plan.ownerURI,
                                              currency: destination.currencyUnit, context: context)
    guard sender.objectID != oldDestination.objectID,
          sender.objectID != newDestination.objectID,
          oldDestination.objectID != newDestination.objectID else {
        throw HostError.message("W10 sender, current recipient and target accounts must be distinct")
    }
    return (sender, oldDestination, newDestination)
}

func verifyTransferLegSnapshot(_ object: NSManagedObject, snapshot: TransferLegSnapshot,
                               account: NSManagedObject, owner: NSManagedObject) throws {
    let expectedAmount = try decimalValue(snapshot.amount, field: "W10 amount")
    let expectedPeerAmount = try decimalValue(snapshot.peerAmount, field: "W10 peer amount")
    let expectedOriginalAmount = try decimalValue(snapshot.originalAmount, field: "W10 original amount")
    let expectedFee = try decimalValue(snapshot.fee, field: "W10 fee")
    let expectedOriginalFee = try decimalValue(snapshot.originalFee, field: "W10 original fee")
    let expectedRate = try decimalValue(snapshot.exchangeRate, field: "W10 exchange rate")
    guard object.entity.name == snapshot.transactionEntity,
          object.value(forKey: "GID") as? String == snapshot.transactionGID,
          durableNumericID(object.objectID) == snapshot.transactionNumericID,
          (object.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
          object.value(forKey: "originalCurrency") as? String == snapshot.currencyUnit,
          object.value(forKey: snapshot.transactionEntity == "TransferWithdrawTransaction"
            ? "originalRecipientCurrency" : "originalSenderCurrency") as? String == snapshot.peerCurrencyUnit,
          try nativeDecimal(object, "amount") == expectedAmount,
          try nativeDecimal(object, "originalAmount") == expectedOriginalAmount,
          try nativeDecimal(object, snapshot.transactionEntity == "TransferWithdrawTransaction"
            ? "originalRecipientAmount" : "originalSenderAmount") == expectedPeerAmount,
          try nativeDecimal(object, "fee") == expectedFee,
          try nativeDecimal(object, "originalFee") == expectedOriginalFee,
          object.value(forKey: "originalFeeCurrency") as? String == snapshot.originalFeeCurrency,
          try nativeDecimal(object, "originalExchangeRate") == expectedRate,
          try nativeDecimal(object, "currencyExchangeRate") == expectedRate,
          (object.value(forKey: "status") as? NSNumber)?.intValue == snapshot.status,
          (object.value(forKey: "flags") as? NSNumber)?.intValue == snapshot.flags,
          (object.value(forKey: "reconciled") as? NSNumber)?.boolValue == snapshot.reconciled,
          object.value(forKey: "notes") as? String == snapshot.note,
          object.value(forKey: "desc") as? String == snapshot.description,
          payeeGID(object) == snapshot.payeeGID,
          let date = object.value(forKey: "date") as? Date,
          abs(date.timeIntervalSince(try precisePlanTimestamp(snapshot.occurredAt))) < 0.000001 else {
        throw HostError.message("W10 transfer leg differs from its reviewed snapshot")
    }
    let tags = try relatedObjects(object, "tags").map { tag -> String in
        guard let gid = tag.value(forKey: "GID") as? String,
              (tag.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID else {
            throw HostError.message("W10 tag is missing a same-owner GID")
        }
        return gid
    }.sorted()
    guard tags == snapshot.tagGIDs,
          try relatedObjects(object, "categoriesAssigments").map({ $0.objectID.uriRepresentation().absoluteString }).sorted()
            == snapshot.categoryAssignmentURIs else {
        throw HostError.message("W10 transfer tags or category assignments differ from the reviewed snapshot")
    }
}

func transferRecipientEditPostcondition(_ plan: WriterPlanV2,
                                        operation: WriterOperationV2) throws -> TransferRecipientEditPostcondition {
    guard let pair = operation.expectedPair,
          let previous = plan.previousDestinationAccount,
          let destination = plan.destinationAccount else {
        throw HostError.message("W10 postcondition is incomplete")
    }
    return TransferRecipientEditPostcondition(
        senderGID: pair.sender.transactionGID,
        recipientGID: pair.recipient.transactionGID,
        senderAccountGID: pair.sender.accountGID,
        previousDestinationAccountGID: previous.accountGID,
        destinationAccountGID: destination.accountGID,
        recipientAmount: pair.recipient.amount,
        receiveAt: pair.recipient.occurredAt)
}

func transferRecipientEditReceipt(_ plan: WriterPlanV2, operation: WriterOperationV2,
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
        item.transferRecipientEditPostcondition = try transferRecipientEditPostcondition(plan, operation: operation)
        item.transferRecipientEditDetails = TransferRecipientEditDetails(
            recipientGID: operation.recipientTransactionGID!,
            recipientNumericID: durableNumericID(recipient.objectID),
            recipientURI: recipient.objectID.uriRepresentation().absoluteString)
    }
    return WriterResultV2(contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
        classification: classification, verified: success, operations: [item])
}

func inspectTransferRecipientEdit(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                                  saved: Bool = false) throws -> TransferRecipientEditInspection {
    let operation = plan.operations[0]
    guard let pair = operation.expectedPair,
          let previous = plan.previousDestinationAccount,
          let destination = plan.destinationAccount else {
        throw HostError.message("W10 missing expected pair or destination accounts")
    }
    let (senderAccount, oldDestination, newDestination) = try transferRecipientEditAccounts(plan, context: context)
    let sender = try fetchExactObject(entityName: pair.sender.transactionEntity,
                                     gid: pair.sender.transactionGID, context: context)
    let recipient = try fetchExactObject(entityName: pair.recipient.transactionEntity,
                                        gid: pair.recipient.transactionGID, context: context)
    guard let senderOwner = senderAccount.value(forKey: "user") as? NSManagedObject,
          senderOwner.objectID.uriRepresentation().absoluteString == plan.ownerURI else {
        throw HostError.message("W10 sender account owner differs from the reviewed plan")
    }
    let recipientAccount = recipient.value(forKey: "account") as? NSManagedObject
    let senderRecipientAccount = sender.value(forKey: "recipientAccount") as? NSManagedObject
    let before = recipientAccount?.objectID == oldDestination.objectID
        && senderRecipientAccount?.objectID == oldDestination.objectID
    let after = recipientAccount?.objectID == newDestination.objectID
        && senderRecipientAccount?.objectID == newDestination.objectID
    let amount = try decimalValue(pair.recipient.amount, field: "W10 recipient amount")
    let sourcePrior = try decimalValue(plan.expectedCachedAccountBalance, field: "W10 source balance")
    let oldPrior = try decimalValue(previous.expectedCachedBalance, field: "W10 previous destination balance")
    let newPrior = try decimalValue(destination.expectedCachedBalance, field: "W10 target destination balance")
    let fixtureCache = usesFixtureBalanceCache(context)
    let sourceBalance = try nativeDecimal(senderAccount, "ballance")
    let oldBalance = try nativeDecimal(oldDestination, "ballance")
    let newBalance = try nativeDecimal(newDestination, "ballance")
    let beforeBalances = sourceBalance == sourcePrior && oldBalance == oldPrior && newBalance == newPrior
    let afterBalances = sourceBalance == sourcePrior
        && oldBalance == (fixtureCache ? oldPrior - amount : oldPrior)
        && newBalance == (fixtureCache ? newPrior + amount : newPrior)
    guard sender.objectID != recipient.objectID,
          (sender.value(forKey: "account") as? NSManagedObject)?.objectID == senderAccount.objectID,
          (recipient.value(forKey: "senderAccount") as? NSManagedObject)?.objectID == senderAccount.objectID,
          (sender.value(forKey: "recipientTransaction") as? NSManagedObject)?.objectID == recipient.objectID,
          (recipient.value(forKey: "senderTransaction") as? NSManagedObject)?.objectID == sender.objectID,
          try relatedObjects(sender, "categoriesAssigments").map({ $0.objectID.uriRepresentation().absoluteString }).sorted() == pair.sender.categoryAssignmentURIs,
          try relatedObjects(recipient, "categoriesAssigments").map({ $0.objectID.uriRepresentation().absoluteString }).sorted() == pair.recipient.categoryAssignmentURIs else {
        throw HostError.message("W10 transfer pair links or assignments are not reciprocal")
    }
    try verifyTransferLegSnapshot(sender, snapshot: pair.sender, account: senderAccount, owner: senderOwner)
    try verifyTransferLegSnapshot(recipient, snapshot: pair.recipient,
        account: before ? oldDestination : newDestination, owner: senderOwner)
    guard (before && beforeBalances) || (after && afterBalances) else {
        return TransferRecipientEditInspection(
            receipt: try transferRecipientEditReceipt(plan, operation: operation, classification: "unknown"),
            senderAccount: senderAccount, previousDestinationAccount: oldDestination,
            destinationAccount: newDestination, sender: sender, recipient: recipient,
            alreadyReassigned: after)
    }
    if before {
        guard !saved else { throw HostError.message("W10 persisted recipient reassignment is missing") }
        return TransferRecipientEditInspection(
            receipt: try transferRecipientEditReceipt(plan, operation: operation, classification: "retry_safe"),
            senderAccount: senderAccount, previousDestinationAccount: oldDestination,
            destinationAccount: newDestination, sender: sender, recipient: recipient,
            alreadyReassigned: false)
    }
    return TransferRecipientEditInspection(
        receipt: try transferRecipientEditReceipt(plan, operation: operation, classification: saved ? "applied" : "noop",
            sender: sender, recipient: recipient),
        senderAccount: senderAccount, previousDestinationAccount: oldDestination,
        destinationAccount: newDestination, sender: sender, recipient: recipient,
        alreadyReassigned: true)
}

func transferRecipientEditPreimages(_ inspection: TransferRecipientEditInspection,
                                    context: NSManagedObjectContext) throws -> [CreationPreimage] {
    var allowedByID: [NSManagedObjectID: Set<String>] = [
        inspection.sender.objectID: ["relationship:recipientAccount"],
        inspection.recipient.objectID: ["relationship:account"],
    ]
    for account in [inspection.previousDestinationAccount, inspection.destinationAccount] {
        allowedByID[account.objectID, default: []].formUnion([
            "relationship:transactionsHistory",
            "relationship:reverseTransferWithdrawTransactionrecipientAccount",
        ])
        if usesFixtureBalanceCache(context) { allowedByID[account.objectID, default: []].insert("attribute:ballance") }
    }
    var result: [CreationPreimage] = []
    for entityName in ["SyncObject", "CategoryAssigment"] {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: entityName)) {
            var fingerprint = try immutableTransactionFingerprint(object)
            if object.entity.relationshipsByName["payee"] != nil {
                fingerprint["relationship:payee"] = (object.value(forKey: "payee") as? NSManagedObject)
                    .map { $0.objectID.uriRepresentation().absoluteString as NSString } ?? NSNull()
            }
            let allowed = allowedByID[object.objectID] ?? []
            result.append(CreationPreimage(objectID: object.objectID,
                fingerprint: fingerprint.filter { !allowed.contains($0.key) }, allowedKeys: allowed))
        }
    }
    return result
}

func reassignTransferRecipientV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                                 requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let before = try inspectTransferRecipientEdit(plan, context: context)
    if before.receipt.classification == "noop" { return before.receipt }
    guard before.receipt.classification == "retry_safe" else {
        throw HostError.message("W10 transfer pair, target accounts or balances differ from the reviewed plan")
    }
    let preimages = try transferRecipientEditPreimages(before, context: context)
    let amount = try decimalValue(plan.operations[0].expectedPair!.recipient.amount,
                                  field: "W10 recipient amount")
    try requireStopped()
    before.sender.setValue(before.destinationAccount, forKey: "recipientAccount")
    before.recipient.setValue(before.destinationAccount, forKey: "account")
    if usesFixtureBalanceCache(context) {
        let oldPrior = try decimalValue(plan.previousDestinationAccount!.expectedCachedBalance,
                                        field: "W10 previous destination balance")
        let newPrior = try decimalValue(plan.destinationAccount!.expectedCachedBalance,
                                        field: "W10 target destination balance")
        before.previousDestinationAccount.setValue(nativeDouble(oldPrior - amount), forKey: "ballance")
        before.destinationAccount.setValue(nativeDouble(newPrior + amount), forKey: "ballance")
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
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W10 read-back did not run"))
    readback.performAndWait {
        result = Result {
            let persisted = try inspectTransferRecipientEdit(plan, context: readback, saved: true)
            guard persisted.receipt.classification == "applied" else {
                throw HostError.message("W10 independent transfer-pair read-back differs")
            }
            try verifyCreationPreimages(preimages, context: readback)
            return persisted.receipt
        }
    }
    return try result.get()
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
          try nativeDecimal(object, "currencyExchangeRate") >= 0,
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
    let result = prior + (operation.destinationOld == nil && destination.balanceMode != "ledger" ? amount : 0)
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
    let destinationFinal = destinationPrior + (usesFixtureBalanceCache(context) && operation.destinationOld == nil ? recipientAmount : 0)
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
    if oldRecipient == nil && usesFixtureBalanceCache(context) {
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

func recoverPlanV2(_ plan: WriterPlanV2, container: NSPersistentContainer,
                   requireRuntime: (WriterPlanV2, NSPersistentStoreCoordinator) throws -> Void = requireReviewedRuntime) throws -> WriterResultV2 {
    let context = container.newBackgroundContext()
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("writer v2 recovery did not run"))
    context.performAndWait {
        do {
            try requireRuntime(plan, container.persistentStoreCoordinator)
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
            if extendedAdjustPolicies.values.contains(where: { $0.capability == plan.capability }) {
                result = .success(try inspectExtendedAdjustment(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.delete-adjust-balance-investment-total" {
                result = .success(try inspectDeleteAdjustment(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.delete-supported-transactions" {
                result = .success(try inspectSupportedDeletion(plan, context: context))
                return
            }
            if plan.capability == "write.replace-import-with-transfer" {
                result = .success(try inspectTransfer(plan, context: context).receipt)
                return
            }
            if plan.capability == "write.reassign-transfer-recipient" {
                result = .success(try inspectTransferRecipientEdit(plan, context: context).receipt)
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
    requireStopped: () throws -> Void = requireMoneyWizStopped,
    requireRuntime: (WriterPlanV2, NSPersistentStoreCoordinator) throws -> Void = requireReviewedRuntime
) throws -> WriterResultV2 {
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("writer v2 did not run"))
    context.performAndWait {
        do {
            try requireStopped()
            try requireRuntime(plan, container.persistentStoreCoordinator)
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
            if extendedAdjustPolicies.values.contains(where: { $0.capability == plan.capability }) {
                result = .success(try extendedAdjustmentV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.delete-adjust-balance-investment-total" {
                result = .success(try deleteAdjustmentV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.delete-supported-transactions" {
                result = .success(try deleteSupportedTransactionsV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.replace-import-with-transfer" {
                result = .success(try replaceImportWithTransferV2(plan, context: context, requireStopped: requireStopped))
                return
            }
            if plan.capability == "write.reassign-transfer-recipient" {
                result = .success(try reassignTransferRecipientV2(plan, context: context, requireStopped: requireStopped))
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

let minimumLiveWriterBuild = 449

func isCanonicalMoneyWizStore(_ storeURL: URL, bundleID: String) -> Bool {
    let home = FileManager.default.homeDirectoryForCurrentUser
    let container = home.appendingPathComponent("Library/Containers", isDirectory: true)
        .appendingPathComponent(bundleID, isDirectory: true)
        .appendingPathComponent("Data", isDirectory: true)
    let accepted = [
        container.appendingPathComponent("Library/Application Support/MoneyWiz_iCloud.sqlite"),
        container.appendingPathComponent("Documents/.AppData/ipadMoneyWiz.sqlite"),
    ].map { $0.resolvingSymlinksInPath().standardizedFileURL.path }
    return accepted.contains(storeURL.resolvingSymlinksInPath().standardizedFileURL.path)
}

func requireReviewedApplication(_ identity: AppIdentity, storeUUID: String,
                                checksum: String, storeURL: URL) throws {
    let appURL = URL(fileURLWithPath: identity.path).resolvingSymlinksInPath()
    let modelURL = URL(fileURLWithPath: identity.modelPath).resolvingSymlinksInPath()
    let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
        ofType: NSSQLiteStoreType, at: storeURL, options: nil)
    let disposable = metadata["MoneyWizToolsDisposableFixture"] as? String == "W01-v1"
    let build = Bundle(url: appURL)?.object(forInfoDictionaryKey: "CFBundleVersion") as? String
    let supportsLiveWriter = build.flatMap(Int.init).map { $0 >= minimumLiveWriterBuild } ?? false
    let isLiveStore = isCanonicalMoneyWizStore(storeURL, bundleID: identity.bundleID)
    guard let app = Bundle(url: appURL),
          moneyWizBundleIdentifiers.contains(identity.bundleID),
          app.bundleIdentifier == identity.bundleID,
          app.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String == identity.version,
          modelURL.path.hasPrefix(appURL.path + "/"),
          checksum == supportedWriterPolicy.modelChecksum,
          try readModelChecksum(at: modelURL) == checksum,
          try storeIdentity(at: storeURL) == storeUUID else {
        throw HostError.message("reviewed MoneyWiz application, model or store identity differs")
    }
    guard metadata[modelChecksumMetadataKey] as? String == checksum else {
        throw HostError.message("reviewed store model checksum differs")
    }
    guard disposable || isLiveStore else {
        throw HostError.message("marked disposable fixture required for a store outside the canonical MoneyWiz app container")
    }
    guard disposable || supportsLiveWriter else {
        throw HostError.message("MoneyWiz build is below the minimum live-writer build")
    }
}

func requireReviewedRuntime(_ plan: WriterPlanV2,
                            coordinator: NSPersistentStoreCoordinator) throws {
    guard coordinator.persistentStores.count == 1,
          let storeURL = coordinator.persistentStores[0].url,
          coordinator.managedObjectModel.versionChecksum == plan.modelChecksum else {
        throw HostError.message("writer runtime model or store differs from reviewed plan")
    }
    try requireReviewedApplication(plan.appIdentity, storeUUID: plan.storeIdentity.storeUUID,
        checksum: plan.modelChecksum, storeURL: storeURL)
}

let supportedAccountEntities: Set<String> = [
    "CashAccount", "BankChequeAccount", "BankSavingAccount", "CreditCardAccount",
    "LoanAccount", "InvestmentAccount", "ForexAccount",
]

func reviewedAccount(_ gid: String, ownerURI: String, currency: String,
                     context: NSManagedObjectContext) throws -> NSManagedObject {
    let request = NSFetchRequest<NSManagedObject>(entityName: "Account")
    request.includesSubentities = true
    request.fetchLimit = 2
    request.predicate = NSPredicate(format: "GID == %@", gid)
    let accounts = try context.fetch(request)
    guard accounts.count == 1, let account = accounts.first,
          supportedAccountEntities.contains(account.entity.name ?? ""),
          let owner = account.value(forKey: "user") as? NSManagedObject,
          owner.objectID.uriRepresentation().absoluteString == ownerURI,
          account.value(forKey: "currencyName") as? String == currency,
          (account.value(forKey: "archived") as? NSNumber)?.boolValue == false else {
        throw HostError.message("writer requires an active same-owner same-currency supported account")
    }
    return account
}

// Invented fixture stores exercise cache deltas. Native model-48 accounts derive
// their displayed balance from the ledger and leave this cache untouched.
func usesFixtureBalanceCache(_ context: NSManagedObjectContext) -> Bool {
    guard let coordinator = context.persistentStoreCoordinator,
          coordinator.persistentStores.count == 1 else { return false }
    return coordinator.metadata(for: coordinator.persistentStores[0])[
        "MoneyWizToolsDisposableFixture"] as? String == "W01-v1"
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
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let account = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                      currency: plan.currencyUnit, context: context)
    let owner = account.value(forKey: "user") as! NSManagedObject
    if !usesFixtureBalanceCache(context), operation.reportingExchangeRate == nil {
        throw HostError.message("W01 live creation requires an explicit reviewed reporting exchange rate")
    }
    let amount = try decimalValue(operation.amount!, field: "creation amount")
    let before = try decimalValue(plan.expectedCachedAccountBalance, field: "cached balance")
    let after = before + (usesFixtureBalanceCache(context) ? amount : 0)
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
              [1, 2].contains((withdrawal.value(forKey: "status") as? NSNumber)?.intValue ?? -1),
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
    if let description = operation.description { expectedFixed["desc"] = description }
    if !operation.kind.hasPrefix("investment_") {
        if let description = operation.description { expectedFixed["desc"] = description }
        if let rate = operation.reportingExchangeRate {
            expectedFixed["currencyExchangeRate"] = nativeDouble(try decimalValue(rate, field: "reporting rate"))
        }
        if !usesFixtureBalanceCache(transaction.managedObjectContext!) {
            expectedFixed["status"] = 2
            expectedFixed["notes"] = operation.note ?? ""
            expectedFixed["desc"] = operation.description ?? ""
            expectedFixed["checkbookNumber"] = ""
        }
    }
    if operation.kind.hasPrefix("investment_") {
        let trade = operation.kind == "investment_buy" || operation.kind == "investment_buy_new_holding" || operation.kind == "investment_sell"
        expectedFixed["status"] = 2
        expectedFixed["flags"] = 0
        expectedFixed["reconciled"] = true
        expectedFixed["currencyExchangeRate"] = trade ? 0.0 : 1.0
        expectedFixed["originalExchangeRate"] = trade ? 0.0 : 1.0
        expectedFixed["investmentSymbol"] = operation.investmentSymbol as Any? ?? NSNull()
    }
    if operation.kind == "investment_buy" || operation.kind == "investment_buy_new_holding" || operation.kind == "investment_sell" {
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

func creationPreimages(_ refs: CreationReferences, context: NSManagedObjectContext, creatingHolding: Bool = false) throws -> [CreationPreimage] {
    var results: [CreationPreimage] = []
    for name in ["SyncObject", "User", "CategoryAssigment", "WithdrawRefundTransactionLink"] {
        for object in try context.fetch(NSFetchRequest<NSManagedObject>(entityName: name)) {
            var allowed: Set<String> = []
            if object.objectID == refs.account.objectID { allowed = ["attribute:ballance", "relationship:transactionsHistory"] }
            if creatingHolding && object.objectID == refs.account.objectID { allowed.insert("relationship:investmentHoldings") }
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
    if let description = operation.description { transaction.setValue(description, forKey: "desc") }
    if let rate = operation.reportingExchangeRate {
        transaction.setValue(nativeDouble(try decimalValue(rate, field: "reporting rate")), forKey: "currencyExchangeRate")
    }
    if !usesFixtureBalanceCache(context) {
        transaction.setValue(2, forKey: "status")
        transaction.setValue(operation.description ?? "", forKey: "desc")
        transaction.setValue(operation.note ?? "", forKey: "notes")
        transaction.setValue("", forKey: "checkbookNumber")
    }
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
    if usesFixtureBalanceCache(context) {
        refs.account.setValue(nativeDouble(refs.balanceAfter), forKey: "ballance")
    }
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

let nativeHoldingTypes: Set<String> = [
    "Stock", "Mutual Fund", "Bond", "CD", "Option", "Money Market Fund", "Other",
    "Remic", "Future", "Commodity", "Currency", "Unit Investment Trust",
    "Employee Stock Option", "Insurance Annuity", "Preferred Stock", "ETF", "Warrants",
]

struct HoldingCreation: Encodable {
    let holdingGID: String
    let holdingType: String
    let holdingDescription: String
    let durableNumericID: String
    let durableURI: String

    enum CodingKeys: String, CodingKey {
        case holdingGID = "holding_gid", holdingType = "holding_type", holdingDescription = "holding_description"
        case durableNumericID = "durable_numeric_id", durableURI = "durable_uri"
    }
}

func newInvestmentHoldingAttributes(_ operation: WriterOperationV2, plan: WriterPlanV2) throws -> [String: Any] {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0)!
    let price = nativeDouble(try decimalValue(operation.unitPrice!, field: "W08 first Buy price"))
    let history = NSMutableDictionary()
    history[calendar.startOfDay(for: try planTimestamp(operation.occurredAt!))] = NSNumber(value: price)
    return ["GID": operation.holdingGID!, "symbol": operation.holdingSymbol!,
        "investmentObjectType": 0, "holdingType": operation.holdingType!, "assetClass": "",
        "desc": operation.holdingDescription!, "objectCreationDate": try planTimestamp(plan.createdAt),
        "openningNumberOfShares": 0.0, "pricePerShare": price, "costBasisOfMissingOBShares": 0.0,
        "isFromOnlineBanking": false, "isPricePerShareAvailableOnline": false,
        "manualHistoricalPricesPerShare": history]
}

func verifyNewInvestmentHolding(_ holding: NSManagedObject, operation: WriterOperationV2,
                                plan: WriterPlanV2, account: NSManagedObject) throws {
    guard holding.entity.name == "InvestmentHolding" else { throw HostError.message("W08 new holding GID collides with another entity") }
    let fixed = try newInvestmentHoldingAttributes(operation, plan: plan)
    for (key, attribute) in holding.entity.attributesByName {
        let expected = fixed[key] ?? attribute.defaultValue ?? NSNull()
        guard let expectedObject = expected as? NSObject,
              let actual = (holding.value(forKey: key) ?? NSNull()) as? NSObject,
              actual.isEqual(expectedObject) else {
            throw HostError.message("W08 persisted new holding attribute differs: \(key)")
        }
    }
    for (key, relationship) in holding.entity.relationshipsByName {
        if key == "investmentAccount" {
            guard (holding.value(forKey: key) as? NSManagedObject)?.objectID == account.objectID else {
                throw HostError.message("W08 created holding belongs to another account or owner")
            }
        } else if key == "investmentTransactions" {
            let rows = try relatedObjects(holding, key)
            guard rows.count == 1, let row = rows.first,
                  row.entity.name == "InvestmentBuyTransaction", row.value(forKey: "GID") as? String == operation.transactionGID,
                  (row.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID else {
                throw HostError.message("W08 new holding does not have exactly its first Buy")
            }
        } else if relationship.isToMany {
            guard try relatedObjects(holding, key).isEmpty else { throw HostError.message("W08 created holding has unexpected dependencies") }
        } else if holding.value(forKey: key) != nil {
            throw HostError.message("W08 created holding has an unexpected reference")
        }
    }
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

func investmentLedger(_ account: NSManagedObject, excluding: Set<NSManagedObjectID> = []) throws -> Decimal {
    var total = try nativeDecimal(account, "openingBalance")
    for row in try relatedObjects(account, "transactionsHistory") {
        if excluding.contains(row.objectID) { continue }
        guard (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0 else {
            throw HostError.message("W08 account ledger contains a void row")
        }
        total += try nativeDecimal(row, "amount")
    }
    // The W08 cash contract and native account display are in currency cents.
    // Historical Double rows retain sub-cent representation residue.
    var rounded = Decimal()
    NSDecimalRound(&rounded, &total, 2, .plain)
    return rounded
}

func investmentUnits(_ holding: NSManagedObject, account: NSManagedObject,
                     excluding: Set<NSManagedObjectID> = []) throws -> Decimal {
    if account.entity.name == "ForexAccount" { return try forexUnits(holding, account: account, excluding: excluding) }
    var total = try nativeDecimal(holding, "openningNumberOfShares")
    for row in try relatedObjects(holding, "investmentTransactions") {
        if excluding.contains(row.objectID) { continue }
        guard (row.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
              (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              let entity = row.entity.name,
              ["InvestmentBuyTransaction", "InvestmentSellTransaction", "ReconcileTransaction"].contains(entity) else {
            throw HostError.message("W08 holding history contains unsupported transaction")
        }
        let quantity = try nativeDecimal(row, "numberOfShares")
        if entity == "ReconcileTransaction" {
            guard try nativeDecimal(row, "amount") == 0,
                  try nativeDecimal(row, "reconcileAmount") == 0,
                  row.value(forKey: "symbol") as? String == holding.value(forKey: "symbol") as? String else {
                throw HostError.message("W08 stock quantity adjustment has cash movement or a different symbol")
            }
        } else {
            guard quantity > 0 else { throw HostError.message("W08 holding history has nonpositive units") }
        }
        total += entity == "InvestmentSellTransaction" ? -quantity : quantity
    }
    let units = roundedBalance(total, scale: 8)
    guard units >= 0 else { throw HostError.message("W08 holding has negative derived units") }
    return units
}

func preflightInvestment(_ operation: WriterOperationV2, plan: WriterPlanV2,
                         context: NSManagedObjectContext, alreadyPresent: Bool) throws -> CreationReferences {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W08 missing coordinator") }
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let account = try reviewedAccount(plan.expectedAccountGID, ownerURI: plan.ownerURI,
                                      currency: plan.currencyUnit, context: context)
    guard ["InvestmentAccount", "ForexAccount"].contains(account.entity.name ?? ""),
          try nativeDecimal(account, "ballance") == 0 else {
        throw HostError.message("W08 requires an investment or Forex account with untouched cache")
    }
    let owner = account.value(forKey: "user") as! NSManagedObject
    let holdings = try relatedObjects(account, "investmentHoldings")
    if operation.accountMode == "aggregate" && !holdings.isEmpty {
        throw HostError.message("W08 aggregate account unexpectedly has holdings")
    }
    if operation.accountMode == "units" && holdings.isEmpty && operation.kind != "investment_buy_new_holding" {
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
    if operation.kind == "investment_buy_new_holding" {
        guard account.entity.name == "InvestmentAccount" else {
            throw HostError.message("W08 first Buy creates an investment holding; Forex creation requires native Exchange")
        }
        let candidates = try creationObjects(entity: "SyncObject", gid: operation.holdingGID!, context: context)
        guard candidates.count == (alreadyPresent ? 1 : 0) else {
            throw HostError.message("W08 first Buy holding/source presence is partial or its GID already exists")
        }
        let symbol = operation.holdingSymbol!
        let duplicates = holdings.filter {
            ($0.value(forKey: "symbol") as? String)?.trimmingCharacters(in: planWhitespace)
                .caseInsensitiveCompare(symbol) == .orderedSame
        }
        guard duplicates.count == (alreadyPresent ? 1 : 0),
              !alreadyPresent || duplicates.first?.objectID == candidates.first?.objectID else {
            throw HostError.message("W08 first Buy symbol already belongs to a holding in this account")
        }
        if let selected = candidates.first {
            try verifyNewInvestmentHolding(selected, operation: operation, plan: plan, account: account)
            guard try investmentUnits(selected, account: account) == decimalValue(operation.expectedFinalUnits!, field: "W08 first Buy units") else {
                throw HostError.message("W08 first Buy derived units are stale")
            }
            holding = selected
        }
    } else if let gid = operation.holdingGID {
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
                       classification: String, objectID: NSManagedObjectID?, holding: NSManagedObject? = nil) -> WriterResultV2 {
    let success = classification == "applied" || classification == "noop"
    var item = WriterOperationResultV2(operationID: operation.operationID,
        status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID, durableURI: objectID?.uriRepresentation().absoluteString,
        durableNumericID: objectID.map(durableNumericID), oldPayeeGID: nil, newPayeeGID: nil,
        postcondition: success ? creationPostcondition(operation) : nil)
    if success {
        item.investmentDetails = investmentDetails(operation)
        if operation.kind == "investment_buy_new_holding", let holding {
            item.holdingCreation = HoldingCreation(holdingGID: operation.holdingGID!, holdingType: operation.holdingType!,
                holdingDescription: operation.holdingDescription!, durableNumericID: durableNumericID(holding.objectID),
                durableURI: holding.objectID.uriRepresentation().absoluteString)
        }
    }
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
                             objectID: transaction.objectID, holding: refs.holding)
}

func createInvestmentV2(_ operation: WriterOperationV2, plan: WriterPlanV2,
                        context: NSManagedObjectContext,
                        requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let prior = try inspectInvestment(operation, plan: plan, context: context)
    if prior.classification == "noop" { return prior }
    var refs = try preflightInvestment(operation, plan: plan, context: context, alreadyPresent: false)
    let newHolding = operation.kind == "investment_buy_new_holding"
    let priorHoldingIDs = try relatedObjects(refs.account, "investmentHoldings").map { $0.objectID }
    let preimages = try creationPreimages(refs, context: context, creatingHolding: newHolding)
    if newHolding {
        let holding = NSEntityDescription.insertNewObject(forEntityName: "InvestmentHolding", into: context)
        for (key, value) in try newInvestmentHoldingAttributes(operation, plan: plan) { holding.setValue(value, forKey: key) }
        holding.setValue(refs.account, forKey: "investmentAccount")
        refs.holding = holding
    }
    let row = NSEntityDescription.insertNewObject(forEntityName: operation.transactionEntity, into: context)
    row.setValue(operation.transactionGID, forKey: "GID")
    row.setValue(nativeDouble(refs.amount), forKey: "amount")
    row.setValue(nativeDouble(refs.amount), forKey: "originalAmount")
    row.setValue(plan.currencyUnit, forKey: "originalCurrency")
    let trade = operation.kind == "investment_buy" || operation.kind == "investment_buy_new_holding" || operation.kind == "investment_sell"
    row.setValue(trade ? 0.0 : 1.0, forKey: "originalExchangeRate")
    row.setValue(trade ? 0.0 : 1.0, forKey: "currencyExchangeRate")
    row.setValue(2, forKey: "status")
    row.setValue(0, forKey: "flags")
    row.setValue(true, forKey: "reconciled")
    row.setValue(operation.investmentSymbol, forKey: "investmentSymbol")
    row.setValue(try planTimestamp(operation.occurredAt!), forKey: "date")
    row.setValue(try planTimestamp(plan.createdAt), forKey: "objectCreationDate")
    row.setValue(operation.note, forKey: "notes")
    if let description = operation.description { row.setValue(description, forKey: "desc") }
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
            if newHolding {
                let account = try readback.existingObject(with: refs.account.objectID)
                let expectedIDs = Set(priorHoldingIDs).union([refs.holding!.objectID])
                guard try Set(relatedObjects(account, "investmentHoldings").map { $0.objectID }) == expectedIDs else {
                    throw HostError.message("W08 first Buy changed an unrelated account holding membership")
                }
            }
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
        expectedBalanceDelta: operation.expectedBalanceDelta!,
        description: operation.description, reportingExchangeRate: operation.reportingExchangeRate
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

struct PayeeInventoryItem: Codable, Equatable {
    let relationship: String
    let entity: String
    let objectURI: String
    enum CodingKeys: String, CodingKey {
        case relationship, entity
        case objectURI = "object_uri"
    }
}

struct PayeeInventoryIdentity: Codable, Equatable {
    let gid: String
    let numericID: String
    let name: String
    let objectURI: String
    enum CodingKeys: String, CodingKey {
        case gid, name
        case numericID = "numeric_id", objectURI = "object_uri"
    }
}

struct PayeeInventory: Codable {
    let ownerURI: String
    let source: PayeeInventoryIdentity
    let survivor: PayeeInventoryIdentity
    let references: [PayeeInventoryItem]
    enum CodingKeys: String, CodingKey {
        case ownerURI = "owner_uri", source, survivor, references
    }
}

struct PayeeMergeApproval: Decodable {
    let userID: Int
    let leftID: String
    let leftName: String
    let rightID: String
    let rightName: String
    let reviewDecision: String
    let approvedCanonicalID: String
    let reviewNotes: String
    let mapSHA256: String
    enum CodingKeys: String, CodingKey {
        case userID = "user_id", leftID = "left_id", leftName = "left_name"
        case rightID = "right_id", rightName = "right_name"
        case reviewDecision = "review_decision"
        case approvedCanonicalID = "approved_canonical_id"
        case reviewNotes = "review_notes", mapSHA256 = "map_sha256"
    }
}

struct PayeeMergeOperationV2: Decodable {
    let operationID: String
    let kind: String
    let source: PayeeInventoryIdentity
    let survivor: PayeeInventoryIdentity
    let expectedReferences: [PayeeInventoryItem]
    let evidenceNote: String
    let approval: PayeeMergeApproval?
    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id", kind, source, survivor
        case expectedReferences = "expected_references"
        case evidenceNote = "evidence_note", approval
    }
}

struct PayeeMergePlanV2: Decodable {
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
    let sourceEventID: String
    let merge: PayeeMergeOperationV2
    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version"
        case operationSchemaVersion = "operation_schema_version"
        case planID = "plan_id", planDigest = "plan_digest"
        case profileID = "profile_id", modelChecksum = "model_checksum"
        case storeIdentity = "store_identity", ownerURI = "owner_uri"
        case appIdentity = "app_identity", capability, createdAt = "created_at"
        case sourceEventID = "source_event_id", merge
    }
}

struct PayeeMergeOperationResultV2: Encodable {
    let operationID: String
    let status: String
    let sourcePayeeGID: String
    let survivorPayeeGID: String
    let movedReferences: [PayeeInventoryItem]
    let sourceAbsent: Bool
    let survivorPresent: Bool
    enum CodingKeys: String, CodingKey {
        case operationID = "operation_id", status
        case sourcePayeeGID = "source_payee_gid"
        case survivorPayeeGID = "survivor_payee_gid"
        case movedReferences = "moved_references"
        case sourceAbsent = "source_absent", survivorPresent = "survivor_present"
    }
}

struct PayeeMergeResultV2: Encodable {
    let contractVersion = 2
    let planID: String
    let planDigest: String
    let classification: String
    let verified: Bool
    let operations: [PayeeMergeOperationResultV2]
    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version", planID = "plan_id"
        case planDigest = "plan_digest", classification, verified, operations
    }
}

func isBlankPayeeMergeName(_ name: String) -> Bool {
    name.unicodeScalars.allSatisfy { planWhitespace.contains($0) }
}

func normalizedPayeeMergeName(_ name: String) -> String {
    name.precomposedStringWithCompatibilityMapping.unicodeScalars
        .split { planWhitespace.contains($0) }
        .map { String(String.UnicodeScalarView($0)) }.joined(separator: " ")
        .folding(options: .caseInsensitive, locale: Locale(identifier: "en_US_POSIX"))
}

func validatePayeeMergePlanV2(_ plan: PayeeMergePlanV2, raw: [String: Any]) throws {
    try validatePlanScalarTypes(raw)
    let keys: Set<String> = [
        "contract_version", "operation_schema_version", "plan_id", "plan_digest",
        "profile_id", "model_checksum", "store_identity", "owner_uri",
        "app_identity", "capability", "created_at", "source_event_id", "merge",
    ]
    guard Set(raw.keys) == keys,
          let store = raw["store_identity"] as? [String: Any], Set(store.keys) == ["store_uuid"],
          let app = raw["app_identity"] as? [String: Any],
          Set(app.keys) == ["bundle_id", "version", "path", "model_path"],
          let merge = raw["merge"] as? [String: Any],
          Set(merge.keys) == ["operation_id", "kind", "source", "survivor",
                              "expected_references", "evidence_note", "approval"],
          plan.contractVersion == 2, plan.operationSchemaVersion == 1,
          plan.profileID == supportedWriterPolicy.profileID,
          plan.modelChecksum == supportedWriterPolicy.modelChecksum,
          ["write.merge-exact-payees", "write.merge-approved-fuzzy-payees"].contains(plan.capability),
          moneyWizBundleIdentifiers.contains(plan.appIdentity.bundleID),
          !isBlank(plan.planID), !isBlank(plan.sourceEventID),
          !isBlank(plan.ownerURI), !isBlank(plan.merge.operationID),
          !isBlank(plan.merge.evidenceNote),
          plan.planDigest == (try canonicalV2Digest(raw)) else {
        throw HostError.message("W09 plan has an invalid envelope or digest")
    }
    _ = try planTimestamp(plan.createdAt)
    let expectedOwnerPrefix = "x-coredata://\(plan.storeIdentity.storeUUID)/User/p"
    guard plan.ownerURI.hasPrefix(expectedOwnerPrefix),
          Int(plan.ownerURI.dropFirst(expectedOwnerPrefix.count)).map({ $0 > 0 }) == true else {
        throw HostError.message("W09 owner does not identify the reviewed store")
    }
    for (name, payee) in [("source", plan.merge.source), ("survivor", plan.merge.survivor)] {
        guard let rawPayee = merge[name] as? [String: Any],
              Set(rawPayee.keys) == ["gid", "numeric_id", "name", "object_uri"],
              !isBlank(payee.gid), !isBlankPayeeMergeName(payee.name),
              Int(payee.numericID).map({ $0 > 0 }) == true,
              payee.objectURI == "x-coredata://\(plan.storeIdentity.storeUUID)/Payee/p\(payee.numericID)" else {
            throw HostError.message("W09 payee identity is incomplete")
        }
    }
    guard plan.merge.source.gid != plan.merge.survivor.gid,
          plan.merge.source.numericID != plan.merge.survivor.numericID else {
        throw HostError.message("W09 requires distinct source and survivor")
    }
    let exact = normalizedPayeeMergeName(plan.merge.source.name) ==
        normalizedPayeeMergeName(plan.merge.survivor.name)
    guard (plan.capability == "write.merge-exact-payees") == exact,
          plan.merge.kind == (exact ? "merge_exact_payee" : "merge_approved_fuzzy_payee") else {
        throw HostError.message("W09 merge kind differs from current names")
    }
    let allowed: Set<String> = ["transactions", "stringHistoryItems",
                                "scheduledTransactions", "connectedPaymentPlans", "infoCards"]
    var keysSeen: [String] = []
    for (index, reference) in plan.merge.expectedReferences.enumerated() {
        guard let rawReferences = merge["expected_references"] as? [[String: Any]],
              rawReferences.count == plan.merge.expectedReferences.count,
              Set(rawReferences[index].keys) == ["relationship", "entity", "object_uri"],
              allowed.contains(reference.relationship),
              !isBlank(reference.entity),
              reference.objectURI.hasPrefix("x-coredata://\(plan.storeIdentity.storeUUID)/\(reference.entity)/p") else {
            throw HostError.message("W09 reference inventory has an invalid member")
        }
        keysSeen.append("\(reference.relationship)\u{0000}\(reference.entity)\u{0000}\(reference.objectURI)")
    }
    guard keysSeen == Array(Set(keysSeen)).sorted() else {
        throw HostError.message("W09 reference inventory must be unique and sorted")
    }
    if exact {
        guard merge["approval"] is NSNull, plan.merge.approval == nil else {
            throw HostError.message("W09 exact merge cannot carry fuzzy approval")
        }
    } else {
        guard let rawApproval = merge["approval"] as? [String: Any],
              Set(rawApproval.keys) == ["user_id", "left_id", "left_name", "right_id",
                                       "right_name", "review_decision", "approved_canonical_id",
                                       "review_notes", "map_sha256"],
              let approval = plan.merge.approval,
              approval.userID == Int(plan.ownerURI.split(separator: "p").last ?? ""),
              Set([approval.leftID, approval.rightID]) ==
                  Set([plan.merge.source.numericID, plan.merge.survivor.numericID]),
              approval.leftName == (approval.leftID == plan.merge.source.numericID
                                    ? plan.merge.source.name : plan.merge.survivor.name),
              approval.rightName == (approval.rightID == plan.merge.source.numericID
                                     ? plan.merge.source.name : plan.merge.survivor.name),
              approval.reviewDecision == "approved",
              approval.approvedCanonicalID == plan.merge.survivor.numericID,
              !isBlank(approval.reviewNotes),
              approval.mapSHA256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
            throw HostError.message("W09 fuzzy merge lacks an exact approved review row")
        }
    }
}

func optionalPayee(gid: String, context: NSManagedObjectContext) throws -> NSManagedObject? {
    let request = NSFetchRequest<NSManagedObject>(entityName: "Payee")
    request.predicate = NSPredicate(format: "GID == %@", gid)
    request.fetchLimit = 2
    let matches = try context.fetch(request)
    guard matches.count <= 1 else { throw HostError.message("W09 payee GID is ambiguous") }
    return matches.first
}

func payeeMergeResult(_ plan: PayeeMergePlanV2, classification: String,
                      references: [PayeeInventoryItem]) -> PayeeMergeResultV2 {
    PayeeMergeResultV2(
        planID: plan.planID, planDigest: plan.planDigest, classification: classification,
        verified: classification == "applied" || classification == "noop",
        operations: [PayeeMergeOperationResultV2(
            operationID: plan.merge.operationID, status: classification,
            sourcePayeeGID: plan.merge.source.gid,
            survivorPayeeGID: plan.merge.survivor.gid,
            movedReferences: references,
            sourceAbsent: classification == "applied" || classification == "noop",
            survivorPresent: true
        )]
    )
}

func resolvePayeeReference(_ reference: PayeeInventoryItem,
                           context: NSManagedObjectContext) throws -> NSManagedObject {
    guard let url = URL(string: reference.objectURI),
          let objectID = context.persistentStoreCoordinator?.managedObjectID(forURIRepresentation: url),
          objectID.entity.name == reference.entity else {
        throw HostError.message("W09 reference URI does not resolve in the reviewed store")
    }
    return try context.existingObject(with: objectID)
}

func inspectPayeeMerge(_ plan: PayeeMergePlanV2,
                       context: NSManagedObjectContext) throws -> PayeeMergeResultV2 {
    guard let coordinator = context.persistentStoreCoordinator,
          coordinator.persistentStores.count == 1,
          let storeURL = coordinator.persistentStores[0].url,
          coordinator.managedObjectModel.versionChecksum == plan.modelChecksum else {
        throw HostError.message("W09 runtime model or store differs from reviewed plan")
    }
    try requireReviewedApplication(plan.appIdentity, storeUUID: plan.storeIdentity.storeUUID,
        checksum: plan.modelChecksum, storeURL: storeURL)
    let source = try optionalPayee(gid: plan.merge.source.gid, context: context)
    guard let survivor = try optionalPayee(gid: plan.merge.survivor.gid, context: context),
          survivor.objectID.uriRepresentation().absoluteString == plan.merge.survivor.objectURI,
          survivor.value(forKey: "name") as? String == plan.merge.survivor.name,
          (survivor.value(forKey: "user") as? NSManagedObject)?.objectID
              .uriRepresentation().absoluteString == plan.ownerURI else {
        throw HostError.message("W09 survivor changed or disappeared")
    }
    if let source {
        let current = try payeeInventory(sourceGID: plan.merge.source.gid,
                                         survivorGID: plan.merge.survivor.gid, context: context)
        guard current.ownerURI == plan.ownerURI,
              current.source == plan.merge.source,
              current.survivor == plan.merge.survivor,
              current.references == plan.merge.expectedReferences,
              source.objectID.uriRepresentation().absoluteString == plan.merge.source.objectURI else {
            throw HostError.message("W09 reviewed payee or complete reference inventory is stale")
        }
        return payeeMergeResult(plan, classification: "retry_safe", references: [])
    }
    for reference in plan.merge.expectedReferences {
        let object = try resolvePayeeReference(reference, context: context)
        guard let relation = survivor.entity.relationshipsByName[reference.relationship],
              let inverse = relation.inverseRelationship,
              (inverse.isToMany
                  ? (object.value(forKey: inverse.name) as? NSSet)?.contains(survivor) == true
                  : (object.value(forKey: inverse.name) as? NSManagedObject)?.objectID == survivor.objectID) else {
            throw HostError.message("W09 deleted source has an incomplete reference migration")
        }
    }
    return payeeMergeResult(plan, classification: "noop",
                            references: plan.merge.expectedReferences)
}

func recoverPayeeMergeV2(_ plan: PayeeMergePlanV2,
                         container: NSPersistentContainer) throws -> PayeeMergeResultV2 {
    let context = container.newBackgroundContext()
    var result: Result<PayeeMergeResultV2, Error> = .failure(HostError.message("W09 recovery did not run"))
    context.performAndWait { result = Result { try inspectPayeeMerge(plan, context: context) } }
    return try result.get()
}

func writePayeeMergeV2(_ plan: PayeeMergePlanV2, container: NSPersistentContainer,
                       requireStopped: () throws -> Void = requireMoneyWizStopped) throws -> PayeeMergeResultV2 {
    let coordinator = container.persistentStoreCoordinator
    guard coordinator.persistentStores.count == 1,
          let storeURL = coordinator.persistentStores[0].url,
          coordinator.managedObjectModel.versionChecksum == plan.modelChecksum else {
        throw HostError.message("W09 runtime model or store differs from reviewed plan")
    }
    try requireReviewedApplication(plan.appIdentity, storeUUID: plan.storeIdentity.storeUUID,
        checksum: plan.modelChecksum, storeURL: storeURL)
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<PayeeMergeResultV2, Error> = .failure(HostError.message("W09 merge did not run"))
    context.performAndWait {
        result = Result {
            try requireStopped()
            let state = try inspectPayeeMerge(plan, context: context)
            if state.classification == "noop" { return state }
            guard let source = try optionalPayee(gid: plan.merge.source.gid, context: context),
                  let survivor = try optionalPayee(gid: plan.merge.survivor.gid, context: context) else {
                throw HostError.message("W09 payee disappeared after preflight")
            }
            for reference in plan.merge.expectedReferences {
                let object = try resolvePayeeReference(reference, context: context)
                guard let relation = source.entity.relationshipsByName[reference.relationship],
                      let inverse = relation.inverseRelationship else {
                    throw HostError.message("W09 reference relationship changed")
                }
                if inverse.isToMany {
                    let members = object.mutableSetValue(forKey: inverse.name)
                    members.remove(source)
                    members.add(survivor)
                } else {
                    object.setValue(survivor, forKey: inverse.name)
                }
            }
            context.delete(source)
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
            var verified: Result<PayeeMergeResultV2, Error> =
                .failure(HostError.message("W09 fresh-context read-back did not run"))
            readback.performAndWait {
                verified = Result { try inspectPayeeMerge(plan, context: readback) }
            }
            guard try verified.get().classification == "noop" else {
                throw HostError.message("W09 fresh-context read-back differs from reviewed merge")
            }
            return payeeMergeResult(plan, classification: "applied",
                                    references: plan.merge.expectedReferences)
        }
    }
    return try result.get()
}

func payeeInventory(sourceGID: String, survivorGID: String,
                    context: NSManagedObjectContext) throws -> PayeeInventory {
    guard sourceGID != survivorGID, !isBlank(sourceGID), !isBlank(survivorGID) else {
        throw HostError.message("W09 inventory requires two distinct payees")
    }
            let source = try fetchExactObject(entityName: "Payee", gid: sourceGID, context: context)
            let survivor = try fetchExactObject(entityName: "Payee", gid: survivorGID, context: context)
            guard let owner = source.value(forKey: "user") as? NSManagedObject,
                  (survivor.value(forKey: "user") as? NSManagedObject)?.objectID == owner.objectID,
                  owner.entity.name == "User" else {
                throw HostError.message("W09 payees must belong to one user")
            }
            let relationshipNames: Set<String> = [
                "transactions", "stringHistoryItems", "scheduledTransactions",
                "connectedPaymentPlans", "infoCards", "user",
            ]
            guard Set(source.entity.relationshipsByName.keys) == relationshipNames else {
                throw HostError.message("W09 model has an unreviewed payee relationship")
            }
            func identity(_ payee: NSManagedObject) throws -> PayeeInventoryIdentity {
                guard let gid = payee.value(forKey: "GID") as? String,
                      let name = payee.value(forKey: "name") as? String,
                      !isBlank(gid), !isBlankPayeeMergeName(name) else {
                    throw HostError.message("W09 payee identity is incomplete")
                }
                return PayeeInventoryIdentity(
                    gid: gid, numericID: durableNumericID(payee.objectID), name: name,
                    objectURI: payee.objectID.uriRepresentation().absoluteString
                )
            }
            var references: [PayeeInventoryItem] = []
            for relationship in relationshipNames.subtracting(["user"]).sorted() {
                guard let objects = source.value(forKey: relationship) as? NSSet else {
                    throw HostError.message("W09 payee reference inventory is incomplete")
                }
                for case let object as NSManagedObject in objects {
                    guard let entity = object.entity.name,
                          let inverse = source.entity.relationshipsByName[relationship]?.inverseRelationship,
                          (inverse.isToMany
                              ? (object.value(forKey: inverse.name) as? NSSet)?.contains(source) == true
                              : (object.value(forKey: inverse.name) as? NSManagedObject)?.objectID == source.objectID) else {
                        throw HostError.message("W09 payee inverse relationship is inconsistent")
                    }
                    references.append(PayeeInventoryItem(
                        relationship: relationship, entity: entity,
                        objectURI: object.objectID.uriRepresentation().absoluteString
                    ))
                }
            }
            references.sort {
                ($0.relationship, $0.entity, $0.objectURI) <
                    ($1.relationship, $1.entity, $1.objectURI)
            }
            return PayeeInventory(
                ownerURI: owner.objectID.uriRepresentation().absoluteString,
                source: try identity(source), survivor: try identity(survivor),
                references: references
            )
}

func inspectPayeeInventory(_ arguments: [String]) throws -> PayeeInventory {
    guard arguments.count == 9,
          arguments[0] == "--coredata-payee-inventory",
          arguments[1] == "--store", arguments[3] == "--model",
          arguments[5] == "--source", arguments[7] == "--survivor" else {
        throw HostError.message("usage: MoneyWizTools --coredata-payee-inventory --store PATH --model PATH --source GID --survivor GID")
    }
    let container = try loadContainer(
        storeURL: URL(fileURLWithPath: arguments[2]),
        modelURL: URL(fileURLWithPath: arguments[4]),
        expectedChecksum: supportedWriterPolicy.modelChecksum, readOnly: true
    )
    let context = container.newBackgroundContext()
    var result: Result<PayeeInventory, Error> = .failure(HostError.message("W09 inventory did not run"))
    context.performAndWait {
        result = Result {
            try payeeInventory(sourceGID: arguments[6], survivorGID: arguments[8], context: context)
        }
    }
    return try result.get()
}

// W06 inventories are read-only. They bind the complete native deletion closure
// and the projected inverse relationships without executing a Core Data delete.
struct DeletionObjectState: Codable, Equatable {
    let entity: String
    let gid: String?
    let objectURI: String
    let fingerprint: String
    let finalFingerprint: String?
    enum CodingKeys: String, CodingKey {
        case entity, gid, objectURI = "object_uri", fingerprint
        case finalFingerprint = "final_fingerprint"
    }
}

struct DeletionTargetState: Codable, Equatable {
    let object: DeletionObjectState
    let accountGID: String
    let amount: String
    let holdingGID: String?
    let signedUnits: String
    let description: String
    enum CodingKeys: String, CodingKey {
        case object, accountGID = "account_gid", amount, holdingGID = "holding_gid"
        case signedUnits = "signed_units", description
    }
}

struct DeletionAccountState: Codable, Equatable {
    let objectURI: String
    let gid: String
    let currency: String
    let priorBalance: String
    let finalBalance: String
    let priorCache: String
    let finalCache: String
    enum CodingKeys: String, CodingKey {
        case objectURI = "object_uri", gid, currency
        case priorBalance = "prior_balance", finalBalance = "final_balance"
        case priorCache = "prior_cache", finalCache = "final_cache"
    }
}

struct DeletionHoldingState: Codable, Equatable {
    let objectURI: String
    let gid: String
    let accountGID: String
    let symbol: String
    let assetType: Int
    let priorUnits: String
    let finalUnits: String
    enum CodingKeys: String, CodingKey {
        case objectURI = "object_uri", gid, accountGID = "account_gid", symbol
        case assetType = "asset_type", priorUnits = "prior_units", finalUnits = "final_units"
    }
}

struct SupportedDeletionInventory: Codable, Equatable {
    let ownerURI: String
    let targets: [DeletionTargetState]
    let dependents: [DeletionObjectState]
    let retained: [DeletionObjectState]
    let accounts: [DeletionAccountState]
    let holdings: [DeletionHoldingState]
    enum CodingKeys: String, CodingKey {
        case ownerURI = "owner_uri", targets, dependents, retained, accounts, holdings
    }
}

struct SupportedDeletionPostcondition: Codable {
    struct Account: Codable { let gid: String; let balance: String; let cache: String }
    struct Holding: Codable { let gid: String; let units: String }
    let deletedObjectURIs: [String]
    let retainedVerified: Bool
    let accounts: [Account]
    let holdings: [Holding]
    enum CodingKeys: String, CodingKey {
        case deletedObjectURIs = "deleted_object_uris", retainedVerified = "retained_verified", accounts, holdings
    }
}

func supportedDeletionPostcondition(_ inventory: SupportedDeletionInventory) -> SupportedDeletionPostcondition {
    SupportedDeletionPostcondition(
        deletedObjectURIs: (inventory.targets.map { $0.object.objectURI } + inventory.dependents.map { $0.objectURI }).sorted(),
        retainedVerified: true,
        accounts: inventory.accounts.map { .init(gid: $0.gid, balance: $0.finalBalance, cache: $0.finalCache) },
        holdings: inventory.holdings.map { .init(gid: $0.gid, units: $0.finalUnits) })
}

func validateSupportedDeletionShape(_ raw: [String: Any], plan: WriterPlanV2) throws {
    let required: Set<String> = ["operation_id", "kind", "capability", "transaction_entity", "transaction_gid",
        "owner_uri", "source_event_id", "deletion_reason", "deletion_inventory", "expected_postcondition"]
    guard Set(raw.keys) == required, raw["kind"] as? String == "delete_supported_transactions",
          raw["capability"] as? String == "write.delete-supported-transactions",
          plan.capability == "write.delete-supported-transactions",
          raw["owner_uri"] as? String == plan.ownerURI, raw["source_event_id"] as? String == plan.sourceEventID,
          let reason = raw["deletion_reason"] as? String, !isBlank(reason),
          let graph = raw["deletion_inventory"] as? [String: Any],
          Set(graph.keys) == ["owner_uri", "targets", "dependents", "retained", "accounts", "holdings"],
          graph["owner_uri"] as? String == plan.ownerURI else {
        throw HostError.message("W06 supported deletion shape or envelope differs")
    }
    func objects(_ name: String) throws -> [[String: Any]] {
        guard let items = graph[name] as? [[String: Any]] else { throw HostError.message("W06 \(name) must contain objects") }
        return items
    }
    var seen: Set<String> = []
    var gids: Set<String> = []
    let prefix = "x-coredata://\(plan.storeIdentity.storeUUID)/"
    func uri(_ value: String, entity: String? = nil) throws {
        guard value.hasPrefix(prefix) else { throw HostError.message("W06 object URI has a different store") }
        let tail = String(value.dropFirst(prefix.count))
        let parts = tail.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2, String(parts[0]).range(of: "^[A-Za-z][A-Za-z0-9]*$", options: .regularExpression) != nil,
              String(parts[1]).range(of: "^p[1-9][0-9]*$", options: .regularExpression) != nil,
              entity == nil || String(parts[0]) == entity else { throw HostError.message("W06 object URI identity is invalid") }
    }
    func state(_ item: [String: Any], retained: Bool) throws {
        let keys = Set(["entity", "object_uri", "fingerprint"])
            .union(retained ? ["final_fingerprint"] : [])
        guard Set(item.keys) == keys || Set(item.keys) == keys.union(["gid"]),
              let entity = item["entity"] as? String, !isBlank(entity),
              let identity = item["object_uri"] as? String, seen.insert(identity).inserted else {
            throw HostError.message("W06 object state has unknown, missing or duplicate fields")
        }
        try uri(identity, entity: entity)
        if item.keys.contains("gid") {
            guard let gid = item["gid"] as? String, !isBlank(gid), gids.insert(gid).inserted else {
                throw HostError.message("W06 object GID is missing or duplicated")
            }
        }
        for field in retained ? ["fingerprint", "final_fingerprint"] : ["fingerprint"] {
            guard let hash = item[field] as? String, hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
                throw HostError.message("W06 object fingerprint is invalid")
            }
        }
    }
    let targets = try objects("targets")
    let dependents = try objects("dependents")
    let retained = try objects("retained")
    let accounts = try objects("accounts")
    let holdings = try objects("holdings")
    guard !targets.isEmpty, !accounts.isEmpty, !retained.isEmpty else { throw HostError.message("W06 inventory is incomplete") }
    for target in targets {
        let keys: Set<String> = ["object", "account_gid", "amount", "signed_units", "description"]
        guard Set(target.keys) == keys || Set(target.keys) == keys.union(["holding_gid"]),
              let object = target["object"] as? [String: Any],
              let entity = object["entity"] as? String, supportedDeletionEntities.contains(entity),
              object["gid"] is String, target["account_gid"] is String, target["description"] is String else {
            throw HostError.message("W06 target shape or entity is unsupported")
        }
        try state(object, retained: false)
        for field in ["amount", "signed_units"] {
            guard let text = target[field] as? String,
                  NSDecimalNumber(decimal: try decimalValue(text, field: field)).stringValue == text else {
                throw HostError.message("W06 target decimal is noncanonical")
            }
        }
        if target.keys.contains("holding_gid") {
            guard target["holding_gid"] is String else { throw HostError.message("W06 target holding GID is invalid") }
        } else if target["signed_units"] as? String != "0" { throw HostError.message("W06 units require a holding") }
    }
    for child in dependents {
        try state(child, retained: false)
        guard ["CategoryAssigment", "TransactionBudgetLink", "Image", "WithdrawRefundTransactionLink"].contains(child["entity"] as? String ?? "") else {
            throw HostError.message("W06 dependent entity is unsupported")
        }
    }
    for item in retained { try state(item, retained: true) }
    let retainedMap = Dictionary(uniqueKeysWithValues: retained.map { ($0["object_uri"] as! String, $0) })
    var accountGIDs: Set<String> = []
    for item in accounts {
        guard Set(item.keys) == ["object_uri", "gid", "currency", "prior_balance", "final_balance", "prior_cache", "final_cache"],
              let identity = item["object_uri"] as? String, let gid = item["gid"] as? String,
              accountGIDs.insert(gid).inserted, retainedMap[identity]?["gid"] as? String == gid,
              supportedAccountEntities.contains(retainedMap[identity]?["entity"] as? String ?? ""),
              ["GBP", "EUR", "USD", "CAD"].contains(item["currency"] as? String ?? "") else {
            throw HostError.message("W06 account projection identity differs")
        }
        try uri(identity)
        for field in ["prior_balance", "final_balance", "prior_cache", "final_cache"] {
            guard let text = item[field] as? String,
                  NSDecimalNumber(decimal: try decimalValue(text, field: field)).stringValue == text else {
                throw HostError.message("W06 account decimal is noncanonical")
            }
        }
    }
    guard accountGIDs == Set(targets.compactMap { $0["account_gid"] as? String }) else {
        throw HostError.message("W06 affected account inventory differs")
    }
    var holdingGIDs: Set<String> = []
    for item in holdings {
        guard Set(item.keys) == ["object_uri", "gid", "account_gid", "symbol", "asset_type", "prior_units", "final_units"],
              let identity = item["object_uri"] as? String, let gid = item["gid"] as? String,
              holdingGIDs.insert(gid).inserted, retainedMap[identity]?["gid"] as? String == gid,
              accountGIDs.contains(item["account_gid"] as? String ?? ""),
              let symbol = item["symbol"] as? String, !isBlank(symbol),
              [0, 1].contains(item["asset_type"] as? Int ?? -1) else {
            throw HostError.message("W06 holding projection identity differs")
        }
        try uri(identity, entity: "InvestmentHolding")
        for field in ["prior_units", "final_units"] {
            guard let text = item[field] as? String else { throw HostError.message("W06 quantity must be text") }
            let value = try decimalValue(text, field: field)
            guard value >= 0, NSDecimalNumber(decimal: value).stringValue == text else {
                throw HostError.message("W06 quantity is negative or noncanonical")
            }
        }
    }
    guard holdingGIDs == Set(targets.compactMap { $0["holding_gid"] as? String }) else { throw HostError.message("W06 affected holding inventory differs") }
    for items in [targets.map { $0["object"] as! [String: Any] }, dependents, retained, accounts, holdings] {
        let uris = items.map { $0["object_uri"] as! String }
        guard uris == uris.sorted() else { throw HostError.message("W06 inventory order is noncanonical") }
    }
    let inventory = try JSONDecoder().decode(SupportedDeletionInventory.self, from: JSONSerialization.data(withJSONObject: graph))
    let primary = inventory.targets[0]
    guard let account = inventory.accounts.first(where: { $0.gid == primary.accountGID }),
          primary.object.gid == raw["transaction_gid"] as? String,
          primary.object.entity == raw["transaction_entity"] as? String,
          plan.expectedAccountGID == account.gid, plan.currencyUnit == account.currency,
          plan.expectedCachedAccountBalance == account.priorCache,
          let postcondition = raw["expected_postcondition"] as? [String: Any] else {
        throw HostError.message("W06 primary target or account differs from envelope")
    }
    let expected = try JSONSerialization.jsonObject(with: JSONEncoder().encode(supportedDeletionPostcondition(inventory))) as! [String: Any]
    guard try canonicalV2Digest(postcondition) == canonicalV2Digest(expected) else {
        throw HostError.message("W06 postcondition differs from complete deletion")
    }
}

let supportedDeletionEntities: Set<String> = [
    "DepositTransaction", "WithdrawTransaction", "RefundTransaction",
    "TransferWithdrawTransaction", "TransferDepositTransaction", "ReconcileTransaction",
    "InvestmentBuyTransaction", "InvestmentSellTransaction",
]

func deletionRelatedObjects(_ object: NSManagedObject, _ relationship: NSRelationshipDescription) throws -> [NSManagedObject] {
    if relationship.isToMany {
        if relationship.isOrdered, let ordered = object.value(forKey: relationship.name) as? NSOrderedSet {
            let objects = ordered.array.compactMap { $0 as? NSManagedObject }
            guard objects.count == ordered.count else { throw HostError.message("W06 invalid ordered relationship") }
            return objects
        }
        return try relatedObjects(object, relationship.name).sorted {
            $0.objectID.uriRepresentation().absoluteString < $1.objectID.uriRepresentation().absoluteString
        }
    }
    guard let value = object.value(forKey: relationship.name) else { return [] }
    guard let related = value as? NSManagedObject else { throw HostError.message("W06 invalid to-one relationship") }
    return [related]
}

func deletionAttributeValue(_ value: Any?) throws -> Any {
    guard let value else { return NSNull() }
    if value is NSNull { return NSNull() }
    if let date = value as? Date {
        return ["date": NSNumber(value: date.timeIntervalSinceReferenceDate).stringValue]
    }
    if let data = value as? Data { return ["data": data.base64EncodedString()] }
    if let number = value as? NSNumber {
        guard number.doubleValue.isFinite else { throw HostError.message("W06 nonfinite native attribute") }
        return ["number": number.stringValue, "type": String(cString: number.objCType)]
    }
    if let string = value as? String { return ["string": string] }
    if let array = value as? NSArray { return try array.map { try deletionAttributeValue($0) } }
    if let dictionary = value as? NSDictionary {
        // Installed model-48 holdings archive manual prices with NSDate keys.
        // Bind each dated price without converting its native key into a string.
        if dictionary.count > 0 && dictionary.allKeys.allSatisfy({ $0 is Date }) {
            let dates = dictionary.allKeys.map { $0 as! Date }.sorted()
            let entries = try dates.map { date -> [String: Any] in
                guard date.timeIntervalSinceReferenceDate.isFinite else {
                    throw HostError.message("W06 nonfinite historical-price date")
                }
                guard let price = dictionary.object(forKey: date) as? NSNumber,
                      CFGetTypeID(price) != CFBooleanGetTypeID(), price.doubleValue.isFinite else {
                    throw HostError.message("W06 historical-price value must be a finite number")
                }
                return ["date": NSNumber(value: date.timeIntervalSinceReferenceDate).stringValue,
                        "value": try deletionAttributeValue(price)]
            }
            return ["dated_dictionary": entries]
        }
        var result: [String: Any] = [:]
        for (key, item) in dictionary {
            guard let name = key as? String else { throw HostError.message("W06 nonstring native dictionary key") }
            result[name] = try deletionAttributeValue(item)
        }
        return ["dictionary": result]
    }
    throw HostError.message("W06 unsupported native attribute type \(type(of: value))")
}

func deletionFingerprint(_ object: NSManagedObject, excluding: Set<NSManagedObjectID> = [],
                         attributes: [String: Any] = [:]) throws -> String {
    var snapshot: [String: Any] = [:]
    for name in object.entity.attributesByName.keys {
        snapshot["attribute:\(name)"] = try deletionAttributeValue(attributes[name] ?? object.value(forKey: name))
    }
    // Includes payee, unlike immutableTransactionFingerprint's reassignment contract.
    for (name, relationship) in object.entity.relationshipsByName {
        let objects = try deletionRelatedObjects(object, relationship).filter { !excluding.contains($0.objectID) }
        let uris = objects.map { $0.objectID.uriRepresentation().absoluteString }
        snapshot["relationship:\(name)"] = relationship.isToMany ? uris : uris.first.map { $0 as Any } ?? NSNull()
    }
    let data = try JSONSerialization.data(withJSONObject: snapshot, options: [.sortedKeys])
    return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

func deletionObjectState(_ object: NSManagedObject, excluding: Set<NSManagedObjectID>? = nil,
                         attributes: [String: Any] = [:]) throws -> DeletionObjectState {
    guard let entity = object.entity.name, !object.objectID.isTemporaryID else {
        throw HostError.message("W06 requires a durable native object")
    }
    let gid = object.entity.attributesByName["GID"] != nil ? object.value(forKey: "GID") as? String : nil
    return DeletionObjectState(entity: entity, gid: gid,
        objectURI: object.objectID.uriRepresentation().absoluteString,
        fingerprint: try deletionFingerprint(object),
        finalFingerprint: try excluding.map { try deletionFingerprint(object, excluding: $0, attributes: attributes) })
}

func supportedDeletionInventory(gids: [String], context: NSManagedObjectContext) throws -> SupportedDeletionInventory {
    guard !gids.isEmpty, Set(gids).count == gids.count,
          gids.allSatisfy({ !isBlank($0) && $0 == $0.trimmingCharacters(in: planWhitespace) }) else {
        throw HostError.message("W06 requires distinct normalized target GIDs")
    }
    let targets = try gids.map { gid -> NSManagedObject in
        let matches = try creationObjects(entity: "SyncObject", gid: gid, context: context)
        guard matches.count == 1, let row = matches.first else {
            throw HostError.message("W06 target GID \(gid) matched \(matches.count) objects")
        }
        return row
    }
    let targetIDs = Set(targets.map { $0.objectID })
    var accounts: Set<NSManagedObject> = []
    var holdings: Set<NSManagedObject> = []
    var ownerURI: String?
    for row in targets {
        guard supportedDeletionEntities.contains(row.entity.name ?? ""),
              let account = row.value(forKey: "account") as? NSManagedObject,
              let owner = account.value(forKey: "user") as? NSManagedObject,
              let accountGID = account.value(forKey: "GID") as? String,
              let currency = account.value(forKey: "currencyName") as? String,
              ["GBP", "EUR", "USD", "CAD"].contains(currency),
              (row.value(forKey: "voidCheque") as? NSNumber)?.intValue == 0,
              (row.value(forKey: "flags") as? NSNumber)?.intValue == 0,
              [1, 2].contains((row.value(forKey: "status") as? NSNumber)?.intValue ?? -1),
              isBlank(row.value(forKey: "autoSkipLinkedScheduledTransactionGID") as? String ?? "") else {
            throw HostError.message("W06 target has an unsupported type, state or account")
        }
        let observedOwner = owner.objectID.uriRepresentation().absoluteString
        guard ownerURI == nil || ownerURI == observedOwner else { throw HostError.message("W06 targets have different owners") }
        ownerURI = observedOwner
        _ = try reviewedAccount(accountGID, ownerURI: observedOwner, currency: currency, context: context)
        guard try relatedObjects(account, "transactionsHistory").contains(row) else {
            throw HostError.message("W06 target account inverse is inconsistent")
        }
        accounts.insert(account)
        if let holding = row.value(forKey: "investmentHolding") as? NSManagedObject {
            guard (holding.value(forKey: "investmentAccount") as? NSManagedObject)?.objectID == account.objectID,
                  try relatedObjects(account, "investmentHoldings").contains(holding),
                  try relatedObjects(holding, "investmentTransactions").contains(row) else {
                throw HostError.message("W06 holding ownership or inverse is inconsistent")
            }
            holdings.insert(holding)
        } else if ["InvestmentBuyTransaction", "InvestmentSellTransaction"].contains(row.entity.name ?? "") {
            throw HostError.message("W06 trade is missing its holding")
        }
        if row.entity.name == "TransferWithdrawTransaction" || row.entity.name == "TransferDepositTransaction" {
            let outgoing = row.entity.name == "TransferWithdrawTransaction"
            let peerKey = outgoing ? "recipientTransaction" : "senderTransaction"
            let inverseKey = outgoing ? "senderTransaction" : "recipientTransaction"
            let peerAccountKey = outgoing ? "recipientAccount" : "senderAccount"
            let inverseAccountKey = outgoing ? "senderAccount" : "recipientAccount"
            guard let peer = row.value(forKey: peerKey) as? NSManagedObject,
                  peer.entity.name == (outgoing ? "TransferDepositTransaction" : "TransferWithdrawTransaction"),
                  targetIDs.contains(peer.objectID),
                  (peer.value(forKey: inverseKey) as? NSManagedObject)?.objectID == row.objectID,
                  (row.value(forKey: peerAccountKey) as? NSManagedObject)?.objectID ==
                    (peer.value(forKey: "account") as? NSManagedObject)?.objectID,
                  (peer.value(forKey: inverseAccountKey) as? NSManagedObject)?.objectID == account.objectID else {
                throw HostError.message("W06 requires the exact reciprocal transfer pair")
            }
        }
        if row.entity.name == "WithdrawTransaction" || row.entity.name == "RefundTransaction" {
            let withdrawal = row.entity.name == "WithdrawTransaction"
            let key = withdrawal ? "refundTransactionsLinks" : "withdrawTransactionsLinks"
            let links = try relatedObjects(row, key)
            guard withdrawal || !links.isEmpty else { throw HostError.message("W06 refund has no original withdrawal") }
            for link in links {
                guard let original = link.value(forKey: "withdrawTransaction") as? NSManagedObject,
                      let refund = link.value(forKey: "refundTransaction") as? NSManagedObject,
                      original.entity.name == "WithdrawTransaction", refund.entity.name == "RefundTransaction",
                      (withdrawal ? original : refund).objectID == row.objectID,
                      (original.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
                      (refund.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID,
                      try relatedObjects(original, "refundTransactionsLinks").contains(link),
                      try relatedObjects(refund, "withdrawTransactionsLinks").contains(link) else {
                    throw HostError.message("W06 refund dependency is inconsistent")
                }
                guard !withdrawal || targetIDs.contains(refund.objectID) else {
                    throw HostError.message("W06 withdrawal deletion requires explicitly selected dependent refunds")
                }
            }
        }
    }
    var deleted = Set(targets)
    var pending = targets
    let dependentEntities: Set<String> = ["CategoryAssigment", "TransactionBudgetLink", "Image", "WithdrawRefundTransactionLink"]
    while let object = pending.popLast() {
        for relationship in object.entity.relationshipsByName.values {
            for related in try deletionRelatedObjects(object, relationship) {
                guard relationship.deleteRule != .denyDeleteRule,
                      relationship.deleteRule != .noActionDeleteRule else {
                    throw HostError.message("W06 populated relationship has an unsupported deletion rule")
                }
                guard relationship.deleteRule == .cascadeDeleteRule else { continue }
                guard dependentEntities.contains(related.entity.name ?? "") else {
                    throw HostError.message("W06 cascade reaches an unsupported entity")
                }
                // A cascade child must not also own a scheduled/string-history assignment.
                for name in ["scheduledTransacition", "stringHistoryItem"] where related.entity.relationshipsByName[name] != nil {
                    guard related.value(forKey: name) == nil else { throw HostError.message("W06 cascade child is shared with retained history") }
                }
                if deleted.insert(related).inserted { pending.append(related) }
            }
        }
    }
    let deletedIDs = Set(deleted.map { $0.objectID })
    var retained: Set<NSManagedObject> = accounts.union(holdings)
    for object in deleted {
        for relationship in object.entity.relationshipsByName.values {
            for related in try deletionRelatedObjects(object, relationship) where !deletedIDs.contains(related.objectID) {
                guard let inverse = relationship.inverseRelationship,
                      try deletionRelatedObjects(related, inverse).contains(object) else {
                    throw HostError.message("W06 dependent inverse is inconsistent")
                }
                retained.insert(related)
            }
        }
    }
    // Bind the whole affected financial history, so a changed retained row cannot
    // be accepted merely because its contribution rounds to the same balance.
    for account in accounts {
        retained.formUnion(try relatedObjects(account, "transactionsHistory").filter { !deletedIDs.contains($0.objectID) })
        retained.formUnion(try relatedObjects(account, "investmentHoldings"))
    }
    func text(_ value: Decimal) -> String { NSDecimalNumber(decimal: value).stringValue }
    var cacheOverrides: [NSManagedObjectID: [String: Any]] = [:]
    let accountStates = try accounts.map { account -> DeletionAccountState in
        let prior = try investmentLedger(account)
        let final = try investmentLedger(account, excluding: deletedIDs)
        let cache = try nativeDecimal(account, "ballance")
        let delta = try targets.filter { ($0.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID }
            .reduce(Decimal(0)) { try $0 - nativeDecimal($1, "amount") }
        let finalCache = usesFixtureBalanceCache(context) ? cache + delta : cache
        if usesFixtureBalanceCache(context) { cacheOverrides[account.objectID] = ["ballance": nativeDouble(finalCache)] }
        return DeletionAccountState(objectURI: account.objectID.uriRepresentation().absoluteString,
            gid: account.value(forKey: "GID") as! String, currency: account.value(forKey: "currencyName") as! String,
            priorBalance: text(prior), finalBalance: text(final), priorCache: text(cache), finalCache: text(finalCache))
    }.sorted { $0.objectURI < $1.objectURI }
    let holdingStates = try holdings.map { holding -> DeletionHoldingState in
        let account = holding.value(forKey: "investmentAccount") as! NSManagedObject
        guard let gid = holding.value(forKey: "GID") as? String,
              let symbol = holding.value(forKey: "symbol") as? String,
              let assetType = (holding.value(forKey: "investmentObjectType") as? NSNumber)?.intValue,
              assetType == (account.entity.name == "ForexAccount" ? 1 : 0) else {
            throw HostError.message("W06 holding has an unsupported asset identity")
        }
        return DeletionHoldingState(objectURI: holding.objectID.uriRepresentation().absoluteString,
            gid: gid, accountGID: account.value(forKey: "GID") as! String, symbol: symbol, assetType: assetType,
            priorUnits: text(try investmentUnits(holding, account: account)),
            finalUnits: text(try investmentUnits(holding, account: account, excluding: deletedIDs)))
    }.sorted { $0.objectURI < $1.objectURI }
    let targetStates = try targets.map { row -> DeletionTargetState in
        let holding = row.value(forKey: "investmentHolding") as? NSManagedObject
        let units = holding == nil ? Decimal(0) : try nativeDecimal(row, "numberOfShares")
        return DeletionTargetState(object: try deletionObjectState(row),
            accountGID: (row.value(forKey: "account") as! NSManagedObject).value(forKey: "GID") as! String,
            amount: text(try nativeDecimal(row, "amount")), holdingGID: holding?.value(forKey: "GID") as? String,
            signedUnits: text(row.entity.name == "InvestmentSellTransaction" ? -units : units),
            description: row.value(forKey: "desc") as? String ?? "")
    }.sorted { $0.object.objectURI < $1.object.objectURI }
    return SupportedDeletionInventory(ownerURI: ownerURI!, targets: targetStates,
        dependents: try deleted.filter { !targetIDs.contains($0.objectID) }.map { try deletionObjectState($0) }
            .sorted { $0.objectURI < $1.objectURI },
        retained: try retained.map { try deletionObjectState($0, excluding: deletedIDs, attributes: cacheOverrides[$0.objectID] ?? [:]) }
            .sorted { $0.objectURI < $1.objectURI }, accounts: accountStates, holdings: holdingStates)
}

func inspectSupportedDeletionInventory(_ arguments: [String]) throws -> SupportedDeletionInventory {
    guard arguments.count >= 7, arguments.count % 2 == 1,
          arguments[0] == "--coredata-deletion-inventory", arguments[1] == "--store", arguments[3] == "--model",
          stride(from: 5, to: arguments.count, by: 2).allSatisfy({ arguments[$0] == "--target" }) else {
        throw HostError.message("usage: MoneyWizTools --coredata-deletion-inventory --store PATH --model PATH --target GID [--target GID ...]")
    }
    let container = try loadContainer(storeURL: URL(fileURLWithPath: arguments[2]),
        modelURL: URL(fileURLWithPath: arguments[4]), expectedChecksum: supportedWriterPolicy.modelChecksum, readOnly: true)
    let context = container.newBackgroundContext()
    var result: Result<SupportedDeletionInventory, Error> = .failure(HostError.message("W06 inventory did not run"))
    context.performAndWait {
        result = Result { try supportedDeletionInventory(gids: stride(from: 6, to: arguments.count, by: 2).map { arguments[$0] }, context: context) }
    }
    return try result.get()
}

func resolveDeletionObject(_ state: DeletionObjectState, context: NSManagedObjectContext) throws -> NSManagedObject? {
    guard let coordinator = context.persistentStoreCoordinator, let url = URL(string: state.objectURI),
          let identity = coordinator.managedObjectID(forURIRepresentation: url), identity.entity.name == state.entity else {
        throw HostError.message("W06 object URI cannot be resolved in the reviewed store")
    }
    let request = NSFetchRequest<NSManagedObject>(entityName: state.entity)
    request.includesSubentities = false
    request.predicate = NSPredicate(format: "SELF == %@", identity)
    let matches = try context.fetch(request)
    guard matches.count <= 1 else { throw HostError.message("W06 duplicate durable identity") }
    if let gid = state.gid {
        let collisions = try creationObjects(entity: "SyncObject", gid: gid, context: context)
        guard collisions.count == matches.count, collisions.first?.objectID == matches.first?.objectID else {
            throw HostError.message("W06 durable identity or GID was replaced")
        }
    }
    return matches.first
}

func verifySupportedDeletionFinalState(_ inventory: SupportedDeletionInventory,
                                       context: NSManagedObjectContext) throws {
    for state in inventory.retained {
        guard let object = try resolveDeletionObject(state, context: context),
              try deletionFingerprint(object) == state.finalFingerprint else {
            throw HostError.message("W06 retained object differs from its projected state: \(state.objectURI)")
        }
    }
    for state in inventory.accounts {
        let account = try reviewedAccount(state.gid, ownerURI: inventory.ownerURI, currency: state.currency, context: context)
        guard account.objectID.uriRepresentation().absoluteString == state.objectURI,
              try nativeDecimal(account, "ballance") == decimalValue(state.finalCache, field: "W06 final cache"),
              try investmentLedger(account) == decimalValue(state.finalBalance, field: "W06 final balance") else {
            throw HostError.message("W06 final account financial state differs")
        }
    }
    for state in inventory.holdings {
        let holding = try fetchExactObject(entityName: "InvestmentHolding", gid: state.gid, context: context)
        guard holding.objectID.uriRepresentation().absoluteString == state.objectURI,
              let account = holding.value(forKey: "investmentAccount") as? NSManagedObject,
              account.value(forKey: "GID") as? String == state.accountGID,
              holding.value(forKey: "symbol") as? String == state.symbol,
              (holding.value(forKey: "investmentObjectType") as? NSNumber)?.intValue == state.assetType,
              try investmentUnits(holding, account: account) == decimalValue(state.finalUnits, field: "W06 final quantity") else {
            throw HostError.message("W06 final holding state differs")
        }
    }
}

func inspectSupportedDeletion(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                              saved: Bool = false) throws -> WriterResultV2 {
    guard let coordinator = context.persistentStoreCoordinator else { throw HostError.message("W06 missing coordinator") }
    try requireReviewedRuntime(plan, coordinator: coordinator)
    let operation = plan.operations[0]
    guard let inventory = operation.deletionInventory else { throw HostError.message("W06 deletion has no reviewed inventory") }
    let states = inventory.targets.map { $0.object } + inventory.dependents
    let objects = try states.map { try resolveDeletionObject($0, context: context) }
    let present = objects.compactMap { $0 }
    let classification: String
    if present.count == objects.count {
        let observed = try supportedDeletionInventory(gids: inventory.targets.map { $0.object.gid! }, context: context)
        classification = observed == inventory ? "retry_safe" : "unknown"
    } else if present.isEmpty {
        try verifySupportedDeletionFinalState(inventory, context: context)
        classification = saved ? "applied" : "noop"
    } else {
        classification = "unknown"
    }
    let success = classification == "applied" || classification == "noop"
    let primary = inventory.targets[0].object
    var item = WriterOperationResultV2(operationID: operation.operationID,
        status: success ? classification : "unknown", transactionEntity: operation.transactionEntity,
        transactionGID: operation.transactionGID, durableURI: primary.objectURI,
        durableNumericID: primary.objectURI.components(separatedBy: "/p").last,
        oldPayeeGID: nil, newPayeeGID: nil, postcondition: nil)
    if success { item.supportedDeletionPostcondition = supportedDeletionPostcondition(inventory) }
    return WriterResultV2(contractVersion: 2, planID: plan.planID, planDigest: plan.planDigest,
        classification: classification, verified: success, operations: [item])
}

func deleteSupportedTransactionsV2(_ plan: WriterPlanV2, context: NSManagedObjectContext,
                                  requireStopped: () throws -> Void) throws -> WriterResultV2 {
    let before = try inspectSupportedDeletion(plan, context: context)
    if before.classification == "noop" { return before }
    guard before.classification == "retry_safe", let inventory = plan.operations[0].deletionInventory else {
        throw HostError.message("W06 reviewed deletion closure is stale or partially absent")
    }
    // Resolve the entire closure before marking any object for deletion.
    let states = inventory.targets.map { $0.object } + inventory.dependents
    let objects = try states.map { state -> NSManagedObject in
        guard let object = try resolveDeletionObject(state, context: context) else { throw HostError.message("W06 closure changed before deletion") }
        return object
    }
    try requireStopped()
    for object in objects { context.delete(object) }
    if usesFixtureBalanceCache(context) {
        for state in inventory.accounts {
            let account = try reviewedAccount(state.gid, ownerURI: inventory.ownerURI, currency: state.currency, context: context)
            account.setValue(nativeDouble(try decimalValue(state.finalCache, field: "W06 fixture cache")), forKey: "ballance")
        }
    }
    context.processPendingChanges()
    guard Set(context.deletedObjects.map { $0.objectID.uriRepresentation().absoluteString }) ==
          Set(supportedDeletionPostcondition(inventory).deletedObjectURIs) else {
        throw HostError.message("W06 native cascade differs from reviewed closure")
    }
    try verifySupportedDeletionFinalState(inventory, context: context)
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
    var result: Result<WriterResultV2, Error> = .failure(HostError.message("W06 fresh read-back did not run"))
    readback.performAndWait {
        result = Result {
            let verified = try inspectSupportedDeletion(plan, context: readback, saved: true)
            guard verified.classification == "applied" else { throw HostError.message("W06 independent read-back differs") }
            return verified
        }
    }
    return try result.get()
}

func preflightSupportedDeletionAtStore(_ plan: WriterPlanV2, storeURL: URL,
                                       modelURL: URL) throws -> WriterResultV2? {
    // A rejected plan must not enable persistent-history tables by opening the
    // store writable. Inspect first, then repeat all guards in the write context.
    let container = try loadContainer(storeURL: storeURL, modelURL: modelURL,
        expectedChecksum: plan.modelChecksum, readOnly: true)
    let inspection = try recoverPlanV2(plan, container: container)
    if inspection.classification == "noop" { return inspection }
    guard inspection.classification == "retry_safe" else {
        throw HostError.message("W06 reviewed deletion closure is stale or partially absent")
    }
    return nil
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
    if invocation.first == "--coredata-payee-inventory" {
        configureTransformers()
        let inventory = try inspectPayeeInventory(invocation)
        FileHandle.standardOutput.write(try JSONEncoder().encode(inventory))
        FileHandle.standardOutput.write(Data([0x0A]))
        return
    }
    if invocation.first == "--coredata-deletion-inventory" {
        configureTransformers()
        FileHandle.standardOutput.write(try JSONEncoder().encode(inspectSupportedDeletionInventory(invocation)))
        FileHandle.standardOutput.write(Data([0x0A]))
        return
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
        if let capability = rawPlan["capability"] as? String,
           ["write.merge-exact-payees", "write.merge-approved-fuzzy-payees"].contains(capability) {
            let plan = try JSONDecoder().decode(PayeeMergePlanV2.self, from: data)
            try validatePayeeMergePlanV2(plan, raw: rawPlan)
            guard arguments.model.resolvingSymlinksInPath().path ==
                    URL(fileURLWithPath: plan.appIdentity.modelPath).resolvingSymlinksInPath().path else {
                throw HostError.message("W09 selected model differs from reviewed plan")
            }
        try requireReviewedApplication(plan.appIdentity, storeUUID: plan.storeIdentity.storeUUID,
            checksum: plan.modelChecksum, storeURL: arguments.store)
            let container = try loadContainer(
                storeURL: arguments.store, modelURL: arguments.model,
                expectedChecksum: plan.modelChecksum, readOnly: arguments.recoverOnly
            )
            return try JSONEncoder().encode(
                arguments.recoverOnly
                    ? recoverPayeeMergeV2(plan, container: container)
                    : writePayeeMergeV2(plan, container: container)
            )
        }
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
            try requireReviewedApplication(plan.appIdentity, storeUUID: plan.storeIdentity.storeUUID,
                checksum: plan.modelChecksum, storeURL: arguments.store)
        if plan.capability == "write.delete-supported-transactions" && !arguments.recoverOnly,
           let noop = try preflightSupportedDeletionAtStore(plan, storeURL: arguments.store, modelURL: arguments.model) {
            return try JSONEncoder().encode(noop)
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
