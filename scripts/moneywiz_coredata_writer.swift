import CoreData
import Darwin
import Foundation

private let expectedBundleIdentifier = "com.moneywiz.personalfinance-setapp"
private let transactionAuthor = "MWLocalAuthor"

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
    let schemaVersion: Int
    let operations: [WriterOperation]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case operations
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

struct WriterResult: Encodable {
    let createdPayees: Int
    let reassignedTransactions: Int

    enum CodingKeys: String, CodingKey {
        case createdPayees = "created_payees"
        case reassignedTransactions = "reassigned_transactions"
    }
}

enum WriterError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case .message(let message):
            return message
        }
    }
}

func parseArguments() throws -> WriterArguments {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard arguments.count == 6 else {
        throw WriterError.message("usage: MoneyWiz --store PATH --model PATH --plan PATH")
    }

    var values: [String: String] = [:]
    var index = 0
    while index < arguments.count {
        let flag = arguments[index]
        let value = arguments[index + 1]
        guard ["--store", "--model", "--plan"].contains(flag), values[flag] == nil else {
            throw WriterError.message("invalid arguments; expected --store PATH --model PATH --plan PATH")
        }
        values[flag] = value
        index += 2
    }

    guard let storePath = values["--store"],
          let modelPath = values["--model"],
          let planPath = values["--plan"] else {
        throw WriterError.message("missing required --store, --model, or --plan argument")
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
        throw WriterError.message("expected one \(entityName) with GID \(gid), found \(results.count)")
    }
    return object
}

func validateOperation(_ operation: WriterOperation) throws {
    let hasExistingTarget = !(operation.existingPayeeGID?.isEmpty ?? true)
    let hasNewTarget = !(operation.newPayeeKey?.isEmpty ?? true) && !(operation.newPayeeName?.isEmpty ?? true)
    guard hasExistingTarget != hasNewTarget else {
        throw WriterError.message(
            "transaction \(operation.transactionGID) must define exactly one payee target"
        )
    }
}

func loadContainer(storeURL: URL, modelURL: URL) throws -> NSPersistentContainer {
    guard let model = NSManagedObjectModel(contentsOf: modelURL) else {
        throw WriterError.message("cannot load MoneyWiz managed-object model at \(modelURL.path)")
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
        throw WriterError.message("cannot open MoneyWiz database: \(loadError.localizedDescription)")
    }
    return container
}

func writePlan(_ plan: WriterPlan, container: NSPersistentContainer) throws -> WriterResult {
    guard plan.schemaVersion == 1 else {
        throw WriterError.message("unsupported writer plan version \(plan.schemaVersion)")
    }
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<WriterResult, Error> = .failure(WriterError.message("writer did not run"))

    context.performAndWait {
        do {
            var createdPayees: [String: NSManagedObject] = [:]
            var createdPayeeUsers: [String: String] = [:]
            for operation in plan.operations {
                try validateOperation(operation)
                let transaction = try fetchObject(
                    entityName: operation.transactionEntity,
                    gid: operation.transactionGID,
                    context: context
                )

                let targetPayee: NSManagedObject
                if let existingPayeeGID = operation.existingPayeeGID, !existingPayeeGID.isEmpty {
                    targetPayee = try fetchObject(
                        entityName: "Payee", gid: existingPayeeGID, context: context
                    )
                } else {
                    guard let key = operation.newPayeeKey,
                          let name = operation.newPayeeName,
                          !key.isEmpty,
                          !name.isEmpty else {
                        throw WriterError.message(
                            "transaction \(operation.transactionGID) has an incomplete new payee target"
                        )
                    }
                    guard let account = transaction.value(forKey: "account") as? NSManagedObject,
                          let user = account.value(forKey: "user") as? NSManagedObject else {
                        throw WriterError.message(
                            "transaction \(operation.transactionGID) has no account user for new payee creation"
                        )
                    }
                    let userIdentifier = user.objectID.uriRepresentation().absoluteString
                    if let existingCreatedPayee = createdPayees[key] {
                        guard createdPayeeUsers[key] == userIdentifier else {
                            throw WriterError.message(
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
                        payee.setValue(user, forKey: "user")
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
                    reassignedTransactions: plan.operations.count
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
        throw WriterError.message(
            "writer must run from the installed MoneyWizWriter.app compatibility bundle"
        )
    }
    let arguments = try parseArguments()
    guard FileManager.default.fileExists(atPath: arguments.store.path) else {
        throw WriterError.message("database file not found: \(arguments.store.path)")
    }
    guard FileManager.default.fileExists(atPath: arguments.model.path) else {
        throw WriterError.message("managed-object model not found: \(arguments.model.path)")
    }
    let data = try Data(contentsOf: arguments.plan)
    let plan = try JSONDecoder().decode(WriterPlan.self, from: data)
    configureTransformers()
    let container = try loadContainer(storeURL: arguments.store, modelURL: arguments.model)
    let result = try writePlan(plan, container: container)
    let encoded = try JSONEncoder().encode(result)
    FileHandle.standardOutput.write(encoded)
    FileHandle.standardOutput.write(Data([0x0A]))
}

do {
    try run()
} catch {
    let message = "error: \(error.localizedDescription)\n"
    FileHandle.standardError.write(Data(message.utf8))
    exit(2)
}
