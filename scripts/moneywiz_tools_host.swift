import CoreData
import Darwin
import Foundation

private let expectedBundleIdentifier = "com.marcomc.moneywiz-tools"
private let transactionAuthor = "MWLocalAuthor"
private let modelChecksumMetadataKey = "NSStoreModelVersionChecksumKey"
private let supportedProfileChecksums = [
    "moneywiz-2026-model-48": "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
]

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
    let schemaVersion: Int
    let operations: [WriterOperation]
    let payeeMerges: [PayeeMerge]?

    enum CodingKeys: String, CodingKey {
        case contractVersion = "contract_version"
        case profileID = "profile_id"
        case modelChecksum = "model_checksum"
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
    let hasExistingTarget = !(operation.existingPayeeGID?.isEmpty ?? true)
    let hasNewTarget = !(operation.newPayeeKey?.isEmpty ?? true) && !(operation.newPayeeName?.isEmpty ?? true)
    guard hasExistingTarget != hasNewTarget else {
        throw HostError.message(
            "transaction \(operation.transactionGID) must define exactly one payee target"
        )
    }
}

func validatePayeeMerge(_ merge: PayeeMerge) throws {
    guard !merge.sourcePayeeGID.isEmpty,
          !merge.targetPayeeGID.isEmpty,
          merge.sourcePayeeGID != merge.targetPayeeGID else {
        throw HostError.message("payee merge must define two distinct non-empty GIDs")
    }
}

func expectedModelChecksum(for plan: WriterPlan) throws -> String {
    guard plan.contractVersion == 1,
          let expectedChecksum = supportedProfileChecksums[plan.profileID],
          plan.modelChecksum == expectedChecksum else {
        throw HostError.message("unsupported or incomplete Core Data writer contract")
    }
    return expectedChecksum
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

func isPayeeEntity(_ entity: NSEntityDescription?) -> Bool {
    var candidate = entity
    while let current = candidate {
        if current.name == "Payee" {
            return true
        }
        candidate = current.superentity
    }
    return false
}

func inboundPayeeRelationships(
    in model: NSManagedObjectModel
) -> [(NSEntityDescription, NSRelationshipDescription)] {
    var relationships: [(NSEntityDescription, NSRelationshipDescription)] = []
    for entity in model.entities where !entity.isAbstract && entity.name != "Payee" {
        for relationship in entity.relationshipsByName.values
            where isPayeeEntity(relationship.destinationEntity) {
            // This is the Payee.user inverse and is removed naturally when the
            // source payee is deleted. Repointing it would detach the source early.
            if entity.name == "User" && relationship.name == "payees" {
                continue
            }
            relationships.append((entity, relationship))
        }
    }
    return relationships.sorted {
        let leftKey = "\($0.0.name ?? "")::\($0.1.name)"
        let rightKey = "\($1.0.name ?? "")::\($1.1.name)"
        return leftKey < rightKey
    }
}

func objectsReferencing(
    _ source: NSManagedObject,
    entity: NSEntityDescription,
    relationship: NSRelationshipDescription,
    context: NSManagedObjectContext
) throws -> [NSManagedObject] {
    guard let entityName = entity.name else {
        throw HostError.message("payee relationship has no entity name")
    }
    let request = NSFetchRequest<NSManagedObject>(entityName: entityName)
    request.includesSubentities = false
    if relationship.isToMany {
        request.predicate = NSPredicate(
            format: "ANY \(relationship.name) == %@",
            source
        )
    } else {
        request.predicate = NSPredicate(
            format: "%K == %@",
            relationship.name,
            source
        )
    }
    return try context.fetch(request)
}

func migrateInboundPayeeRelationships(
    from source: NSManagedObject,
    to target: NSManagedObject,
    model: NSManagedObjectModel,
    context: NSManagedObjectContext
) throws -> Int {
    var migrated = 0
    for (entity, relationship) in inboundPayeeRelationships(in: model) {
        let objects = try objectsReferencing(
            source,
            entity: entity,
            relationship: relationship,
            context: context
        )
        for object in objects {
            if relationship.isToMany {
                let references = object.mutableSetValue(forKey: relationship.name)
                if references.contains(source) {
                    references.remove(source)
                    references.add(target)
                    migrated += 1
                }
            } else {
                object.setValue(target, forKey: relationship.name)
                migrated += 1
            }
        }
    }
    context.processPendingChanges()
    return migrated
}

func assertNoInboundPayeeReferences(
    _ source: NSManagedObject,
    model: NSManagedObjectModel,
    context: NSManagedObjectContext
) throws {
    for (entity, relationship) in inboundPayeeRelationships(in: model) {
        let remaining = try objectsReferencing(
            source,
            entity: entity,
            relationship: relationship,
            context: context
        )
        if !remaining.isEmpty {
            let entityName = entity.name ?? "<unknown>"
            throw HostError.message(
                "payee merge left \(remaining.count) reference(s) in "
                    + "\(entityName).\(relationship.name)"
            )
        }
    }
}

func mergePayee(
    _ merge: PayeeMerge,
    model: NSManagedObjectModel,
    context: NSManagedObjectContext
) throws -> Int {
    try validatePayeeMerge(merge)
    let source = try fetchObject(
        entityName: "Payee",
        gid: merge.sourcePayeeGID,
        context: context
    )
    let target = try fetchObject(
        entityName: "Payee",
        gid: merge.targetPayeeGID,
        context: context
    )
    guard source.objectID != target.objectID else {
        throw HostError.message("payee merge source and target resolve to the same object")
    }
    guard let sourceUser = source.value(forKey: "user") as? NSManagedObject,
          let targetUser = target.value(forKey: "user") as? NSManagedObject,
          sourceUser.objectID == targetUser.objectID else {
        throw HostError.message("payee merge source and target must belong to the same user")
    }
    let migrated = try migrateInboundPayeeRelationships(
        from: source,
        to: target,
        model: model,
        context: context
    )
    try assertNoInboundPayeeReferences(source, model: model, context: context)
    context.delete(source)
    return migrated
}

func loadContainer(
    storeURL: URL,
    modelURL: URL,
    plan: WriterPlan
) throws -> NSPersistentContainer {
    let expectedChecksum = try expectedModelChecksum(for: plan)
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
    _ = try expectedModelChecksum(for: plan)
    guard plan.schemaVersion == 1 || plan.schemaVersion == 2 else {
        throw HostError.message("unsupported writer plan version \(plan.schemaVersion)")
    }
    let context = container.newBackgroundContext()
    context.transactionAuthor = transactionAuthor
    var result: Result<WriterResult, Error> = .failure(HostError.message("writer did not run"))

    context.performAndWait {
        do {
            var createdPayees: [String: NSManagedObject] = [:]
            var createdPayeeUsers: [String: String] = [:]
            var mergedPayees = 0
            var migratedRelationships = 0
            for operation in plan.operations {
                try validateOperation(operation)
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
            for merge in plan.payeeMerges ?? [] {
                migratedRelationships += try mergePayee(
                    merge,
                    model: container.managedObjectModel,
                    context: context
                )
                mergedPayees += 1
            }
            if context.hasChanges {
                try context.save()
            }
            result = .success(
                WriterResult(
                    createdPayees: createdPayees.count,
                    reassignedTransactions: plan.operations.count,
                    mergedPayees: mergedPayees,
                    migratedRelationships: migratedRelationships
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
    _ = try expectedModelChecksum(for: plan)
    configureTransformers()
    let container = try loadContainer(
        storeURL: arguments.store,
        modelURL: arguments.model,
        plan: plan
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
