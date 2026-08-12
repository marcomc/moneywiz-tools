import AppKit
import CoreData
import Darwin
import Foundation

private let expectedBundleIdentifier = "com.marcomc.moneywiz-tools"
private let moneyWizBundleIdentifiers = [
    "com.moneywiz.personalfinance-setapp",
    "com.moneywiz.personalfinance",
]
private let transactionAuthor = "MWLocalAuthor"
private let modelChecksumMetadataKey = "NSStoreModelVersionChecksumKey"

struct WriterPolicy {
    let profileID: String
    let modelChecksum: String
    let capability: String
    let schemaVersion: Int
}

private let supportedWriterPolicy = WriterPolicy(
    profileID: "moneywiz-2026-model-48",
    modelChecksum: "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
    capability: "write.reassign-payees-by-id",
    schemaVersion: 1
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
    guard invocation.first == "--coredata-write" else {
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
        plan: URL(fileURLWithPath: planPath)
    )
}

func configureTransformers() {
    for name in ["HMRCMappingTransformer", "TransactionsFilterArrayTransformer", "UIColorTransformer"] {
        ValueTransformer.setValueTransformer(
            PassthroughTransformer(), forName: NSValueTransformerName(name)
        )
    }
}

func fetchObject(
    entityName: String,
    gid: String,
    context: NSManagedObjectContext
) throws -> NSManagedObject {
    let request = NSFetchRequest<NSManagedObject>(entityName: entityName)
    request.fetchLimit = 2
    request.predicate = NSPredicate(format: "GID == %@", gid)
    let results = try context.fetch(request)
    guard results.count == 1, let object = results.first else {
        throw HostError.message("expected one \(entityName) with GID \(gid), found \(results.count)")
    }
    return object
}

func validateOperation(_ operation: WriterOperation) throws {
    guard !operation.transactionGID.isEmpty, !operation.transactionEntity.isEmpty else {
        throw HostError.message("writer operation must identify a transaction and entity")
    }
    let hasExistingTarget = !(operation.existingPayeeGID?.isEmpty ?? true)
    let hasNewTarget = !(operation.newPayeeKey?.isEmpty ?? true) && !(operation.newPayeeName?.isEmpty ?? true)
    guard hasExistingTarget != hasNewTarget else {
        throw HostError.message(
            "transaction \(operation.transactionGID) must define exactly one payee target"
        )
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
    for operation in plan.operations {
        try validateOperation(operation)
    }
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
    expectedChecksum: String
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

func writePlan(_ plan: WriterPlan, container: NSPersistentContainer) throws -> WriterResult {
    _ = try validateWriterPlan(plan)
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<WriterResult, Error> = .failure(HostError.message("writer did not run"))

    context.performAndWait {
        do {
            var createdPayees: [String: NSManagedObject] = [:]
            var createdPayeeUsers: [String: String] = [:]
            for operation in plan.operations {
                let transaction = try fetchObject(
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

                let targetPayee: NSManagedObject
                if let existingPayeeGID = operation.existingPayeeGID, !existingPayeeGID.isEmpty {
                    targetPayee = try fetchObject(
                        entityName: "Payee", gid: existingPayeeGID, context: context
                    )
                    guard let payeeUser = targetPayee.value(forKey: "user") as? NSManagedObject,
                          payeeUser.objectID == transactionUser.objectID else {
                        throw HostError.message(
                            "transaction \(operation.transactionGID) and target payee must belong to the same user"
                        )
                    }
                } else {
                    guard let key = operation.newPayeeKey,
                          let name = operation.newPayeeName,
                          !key.isEmpty,
                          !name.isEmpty else {
                        throw HostError.message(
                            "transaction \(operation.transactionGID) has an incomplete new payee target"
                        )
                    }
                    let userIdentifier = transactionUser.objectID.uriRepresentation().absoluteString
                    if let existingCreatedPayee = createdPayees[key] {
                        guard createdPayeeUsers[key] == userIdentifier else {
                            throw HostError.message(
                                "new payee key \(key) resolved to more than one MoneyWiz user"
                            )
                        }
                        targetPayee = existingCreatedPayee
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
                        payee.setValue(transactionUser, forKey: "user")
                        createdPayees[key] = payee
                        createdPayeeUsers[key] = userIdentifier
                        targetPayee = payee
                    }
                }
                transaction.setValue(targetPayee, forKey: "payee")
            }
            if context.hasChanges {
                try context.save()
            }
            result = .success(
                WriterResult(
                    createdPayees: createdPayees.count,
                    reassignedTransactions: plan.operations.count,
                    mergedPayees: 0,
                    migratedRelationships: 0
                )
            )
        } catch {
            context.rollback()
            result = .failure(error)
        }
    }
    return try result.get()
}

func run() throws {
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
    let plan = try JSONDecoder().decode(WriterPlan.self, from: data)
    let expectedChecksum = try validateWriterPlan(plan)
    try requireMoneyWizStopped()
    configureTransformers()
    let container = try loadContainer(
        storeURL: arguments.store,
        modelURL: arguments.model,
        expectedChecksum: expectedChecksum
    )
    let result = try writePlan(plan, container: container)
    let encoded = try JSONEncoder().encode(result)
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
