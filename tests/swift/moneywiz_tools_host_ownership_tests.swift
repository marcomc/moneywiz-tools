import CoreData
import Foundation

enum OwnershipTestError: Error {
    case failure(String)
}

let expectedTransactionEntities: Set<String> = [
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
]

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() {
        throw OwnershipTestError.failure(message)
    }
}

func stringAttribute(_ name: String) -> NSAttributeDescription {
    let attribute = NSAttributeDescription()
    attribute.name = name
    attribute.attributeType = .stringAttributeType
    attribute.isOptional = false
    return attribute
}

func optionalStringAttribute(_ name: String) -> NSAttributeDescription {
    let attribute = stringAttribute(name)
    attribute.isOptional = true
    return attribute
}

func dateAttribute(_ name: String) -> NSAttributeDescription {
    let attribute = NSAttributeDescription()
    attribute.name = name
    attribute.attributeType = .dateAttributeType
    attribute.isOptional = false
    return attribute
}

func doubleAttribute(_ name: String) -> NSAttributeDescription {
    let attribute = NSAttributeDescription()
    attribute.name = name
    attribute.attributeType = .doubleAttributeType
    attribute.isOptional = false
    return attribute
}

func toOneRelationship(
    _ name: String,
    destination: NSEntityDescription,
    optional: Bool = false
) -> NSRelationshipDescription {
    let relationship = NSRelationshipDescription()
    relationship.name = name
    relationship.destinationEntity = destination
    relationship.minCount = optional ? 0 : 1
    relationship.maxCount = 1
    relationship.isOptional = optional
    relationship.deleteRule = .nullifyDeleteRule
    return relationship
}

func makeModel() -> NSManagedObjectModel {
    let user = NSEntityDescription()
    user.name = "User"
    user.managedObjectClassName = "NSManagedObject"

    let account = NSEntityDescription()
    account.name = "Account"
    account.managedObjectClassName = "NSManagedObject"

    let payee = NSEntityDescription()
    payee.name = "Payee"
    payee.managedObjectClassName = "NSManagedObject"

    account.properties = [
        optionalStringAttribute("GID"),
        doubleAttribute("ballance"),
        optionalStringAttribute("currencyName"),
        toOneRelationship("user", destination: user),
    ]
    payee.properties = [
        stringAttribute("GID"),
        stringAttribute("name"),
        dateAttribute("objectCreationDate"),
        toOneRelationship("user", destination: user),
    ]

    let transactionEntities = expectedTransactionEntities.map { name in
        let transaction = NSEntityDescription()
        transaction.name = name
        transaction.managedObjectClassName = "NSManagedObject"
        transaction.properties = [
            stringAttribute("GID"),
            toOneRelationship("account", destination: account),
            toOneRelationship("payee", destination: payee, optional: true),
        ]
        return transaction
    }

    let transactionParent = NSEntityDescription()
    transactionParent.name = "Transaction"
    transactionParent.managedObjectClassName = "NSManagedObject"
    transactionParent.properties = [stringAttribute("GID")]

    let model = NSManagedObjectModel()
    model.entities = [user, account, payee, transactionParent] + transactionEntities
    return model
}

func makeContainer() throws -> NSPersistentContainer {
    let container = NSPersistentContainer(
        name: "MoneyWizOwnershipTests",
        managedObjectModel: makeModel()
    )
    let description = NSPersistentStoreDescription()
    description.type = NSInMemoryStoreType
    description.shouldAddStoreAsynchronously = false
    container.persistentStoreDescriptions = [description]

    var loadError: Error?
    container.loadPersistentStores { _, error in
        loadError = error
    }
    if let loadError {
        throw loadError
    }
    return container
}

func makeSQLiteContainer(at url: URL) throws -> NSPersistentContainer {
    let container = NSPersistentContainer(name: "MoneyWizFoundationSQLite", managedObjectModel: makeModel())
    let description = NSPersistentStoreDescription(url: url)
    description.type = NSSQLiteStoreType
    description.shouldAddStoreAsynchronously = false
    container.persistentStoreDescriptions = [description]
    var loadError: Error?
    container.loadPersistentStores { _, error in loadError = error }
    if let loadError { throw loadError }
    return container
}

func seed(
    _ container: NSPersistentContainer,
    users: [String],
    transactions: [(gid: String, user: String)],
    payees: [(gid: String, user: String)]
) throws {
    let context = container.viewContext
    var userObjects: [String: NSManagedObject] = [:]
    for userID in users {
        userObjects[userID] = NSEntityDescription.insertNewObject(
            forEntityName: "User",
            into: context
        )
    }

    var accounts: [String: NSManagedObject] = [:]
    for userID in users {
        let account = NSEntityDescription.insertNewObject(
            forEntityName: "Account",
            into: context
        )
        account.setValue("account-\(userID)", forKey: "GID")
        account.setValue(0.0, forKey: "ballance")
        account.setValue("EUR", forKey: "currencyName")
        account.setValue(userObjects[userID], forKey: "user")
        accounts[userID] = account
    }

    for payeeSeed in payees {
        let payee = NSEntityDescription.insertNewObject(
            forEntityName: "Payee",
            into: context
        )
        payee.setValue(payeeSeed.gid, forKey: "GID")
        payee.setValue(payeeSeed.gid, forKey: "name")
        payee.setValue(Date(), forKey: "objectCreationDate")
        payee.setValue(userObjects[payeeSeed.user], forKey: "user")
    }

    for transactionSeed in transactions {
        let transaction = NSEntityDescription.insertNewObject(
            forEntityName: "WithdrawTransaction",
            into: context
        )
        transaction.setValue(transactionSeed.gid, forKey: "GID")
        transaction.setValue(accounts[transactionSeed.user], forKey: "account")
    }
    try context.save()
}

func operation(transactionGID: String, payeeGID: String) -> WriterOperation {
    WriterOperation(
        transactionGID: transactionGID,
        transactionEntity: "WithdrawTransaction",
        existingPayeeGID: payeeGID,
        newPayeeKey: nil,
        newPayeeName: nil
    )
}

func operation(
    transactionGID: String,
    entity: String,
    payeeGID: String
) -> WriterOperation {
    WriterOperation(
        transactionGID: transactionGID,
        transactionEntity: entity,
        existingPayeeGID: payeeGID,
        newPayeeKey: nil,
        newPayeeName: nil
    )
}

func newPayeeOperation(
    transactionGID: String,
    key: String,
    name: String
) -> WriterOperation {
    WriterOperation(
        transactionGID: transactionGID,
        transactionEntity: "WithdrawTransaction",
        existingPayeeGID: nil,
        newPayeeKey: key,
        newPayeeName: name
    )
}

func plan(_ operations: [WriterOperation]) -> WriterPlan {
    WriterPlan(
        contractVersion: 1,
        profileID: "moneywiz-2026-model-48",
        modelChecksum: "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        capability: "write.reassign-payees-by-id",
        schemaVersion: 1,
        operations: operations,
        payeeMerges: nil
    )
}

func testWriterContractRequiresExactProfileAndChecksum() throws {
    let valid = plan([operation(transactionGID: "transaction", payeeGID: "payee")])
    let validatedChecksum = try validateWriterPlan(valid)
    try require(
        validatedChecksum == valid.modelChecksum,
        "valid writer profile checksum was rejected"
    )

    let wrongProfile = WriterPlan(
        contractVersion: 1,
        profileID: "future-model",
        modelChecksum: valid.modelChecksum,
        capability: valid.capability,
        schemaVersion: 1,
        operations: valid.operations,
        payeeMerges: nil
    )
    do {
        _ = try validateWriterPlan(wrongProfile)
        throw OwnershipTestError.failure("unknown writer profile unexpectedly succeeded")
    } catch is HostError {
        // Expected.
    }

    let wrongChecksum = WriterPlan(
        contractVersion: 1,
        profileID: valid.profileID,
        modelChecksum: "KxT0qIvWI+7n1S58SHjQOJ8x50TIqI0l+sXzUGx8y18=",
        capability: valid.capability,
        schemaVersion: 1,
        operations: valid.operations,
        payeeMerges: nil
    )
    do {
        _ = try validateWriterPlan(wrongChecksum)
        throw OwnershipTestError.failure("wrong writer checksum unexpectedly succeeded")
    } catch is HostError {
        // Expected.
    }
}

func requireWriterPlanRejected(_ candidate: WriterPlan, _ message: String) throws {
    do {
        _ = try validateWriterPlan(candidate)
        throw OwnershipTestError.failure(message)
    } catch is HostError {
        // Expected.
    }
}

func testWriterPolicyAcceptsExactlyTenTransactionEntities() throws {
    for entity in expectedTransactionEntities {
        let candidate = plan([
            operation(transactionGID: "transaction-\(entity)", entity: entity, payeeGID: "payee")
        ])
        _ = try validateWriterPlan(candidate)
    }

    for entity in ["Payee", "User", "Transaction", "ArbitraryEntity"] {
        try requireWriterPlanRejected(
            plan([
                operation(transactionGID: "transaction", entity: entity, payeeGID: "payee")
            ]),
            "non-transaction entity \(entity) unexpectedly succeeded"
        )
    }
}

func testWriterContractRejectsPartialMixedAndAmbiguousOperations() throws {
    let invalidOperations = [
        WriterOperation(
            transactionGID: "transaction-empty-existing",
            transactionEntity: "WithdrawTransaction",
            existingPayeeGID: " ",
            newPayeeKey: nil,
            newPayeeName: nil
        ),
        WriterOperation(
            transactionGID: "transaction-key-only",
            transactionEntity: "WithdrawTransaction",
            existingPayeeGID: nil,
            newPayeeKey: "key",
            newPayeeName: nil
        ),
        WriterOperation(
            transactionGID: "transaction-name-only",
            transactionEntity: "WithdrawTransaction",
            existingPayeeGID: nil,
            newPayeeKey: nil,
            newPayeeName: "Name"
        ),
        WriterOperation(
            transactionGID: "transaction-mixed",
            transactionEntity: "WithdrawTransaction",
            existingPayeeGID: "payee",
            newPayeeKey: "key",
            newPayeeName: "Name"
        ),
        WriterOperation(
            transactionGID: "  ",
            transactionEntity: "WithdrawTransaction",
            existingPayeeGID: "payee",
            newPayeeKey: nil,
            newPayeeName: nil
        ),
    ]
    for invalidOperation in invalidOperations {
        try requireWriterPlanRejected(
            plan([invalidOperation]),
            "partial, mixed, or blank operation unexpectedly succeeded"
        )
    }

    try requireWriterPlanRejected(
        plan([
            operation(transactionGID: "duplicate", payeeGID: "payee-one"),
            operation(transactionGID: "duplicate", payeeGID: "payee-two"),
        ]),
        "duplicate transaction GID unexpectedly succeeded"
    )
    try requireWriterPlanRejected(
        plan([
            newPayeeOperation(transactionGID: "one", key: "shared", name: "First"),
            newPayeeOperation(transactionGID: "two", key: "shared", name: "Second"),
        ]),
        "one new-payee key mapped to inconsistent names"
    )
}

func testWriterContractRejectsBlockedAndMixedPlanShapes() throws {
    let valid = plan([operation(transactionGID: "transaction", payeeGID: "payee")])
    let merge = PayeeMerge(sourcePayeeGID: "source", targetPayeeGID: "target")

    try requireWriterPlanRejected(
        WriterPlan(
            contractVersion: 1,
            profileID: valid.profileID,
            modelChecksum: valid.modelChecksum,
            capability: "write.merge-duplicate-payees",
            schemaVersion: 2,
            operations: [],
            payeeMerges: [merge]
        ),
        "blocked merge capability unexpectedly succeeded"
    )
    try requireWriterPlanRejected(
        WriterPlan(
            contractVersion: 1,
            profileID: valid.profileID,
            modelChecksum: valid.modelChecksum,
            capability: valid.capability,
            schemaVersion: 1,
            operations: valid.operations,
            payeeMerges: [merge]
        ),
        "mixed reassignment and merge payload unexpectedly succeeded"
    )
    try requireWriterPlanRejected(
        WriterPlan(
            contractVersion: 1,
            profileID: valid.profileID,
            modelChecksum: valid.modelChecksum,
            capability: "write.unknown",
            schemaVersion: 1,
            operations: valid.operations,
            payeeMerges: nil
        ),
        "unknown capability unexpectedly succeeded"
    )
    try requireWriterPlanRejected(
        WriterPlan(
            contractVersion: 1,
            profileID: valid.profileID,
            modelChecksum: valid.modelChecksum,
            capability: valid.capability,
            schemaVersion: 2,
            operations: valid.operations,
            payeeMerges: nil
        ),
        "schema 2 reassignment unexpectedly succeeded"
    )
    try requireWriterPlanRejected(
        WriterPlan(
            contractVersion: 1,
            profileID: valid.profileID,
            modelChecksum: valid.modelChecksum,
            capability: valid.capability,
            schemaVersion: 1,
            operations: [],
            payeeMerges: nil
        ),
        "empty reassignment payload unexpectedly succeeded"
    )
}

func testMoneyWizProcessInspectionFailsClosed() throws {
    var inspectedIdentifiers: [String] = []
    try requireMoneyWizStopped { identifier in
        inspectedIdentifiers.append(identifier)
        return false
    }
    try require(
        Set(inspectedIdentifiers) == Set([
            "com.moneywiz.personalfinance-setapp",
            "com.moneywiz.personalfinance",
        ]),
        "process inspection did not check every known MoneyWiz bundle identifier"
    )

    do {
        try requireMoneyWizStopped { _ in true }
        throw OwnershipTestError.failure("running MoneyWiz unexpectedly succeeded")
    } catch is HostError {
        // Expected.
    }

    do {
        try requireMoneyWizStopped { _ in
            throw OwnershipTestError.failure("inspection failed")
        }
        throw OwnershipTestError.failure("process inspection error unexpectedly succeeded")
    } catch let error as HostError {
        try require(
            error.localizedDescription.contains("cannot verify"),
            "process inspection failure returned the wrong error"
        )
    }
}

func testStoreAndSelectedModelChecksumsMustBothMatch() throws {
    let checksum = "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="
    try validateExactModelChecksum(
        expected: checksum,
        store: checksum,
        selectedModel: checksum
    )

    for (store, selectedModel) in [
        (nil, checksum),
        ("wrong-store-checksum", checksum),
        (checksum, "wrong-model-checksum"),
    ] {
        do {
            try validateExactModelChecksum(
                expected: checksum,
                store: store,
                selectedModel: selectedModel
            )
            throw OwnershipTestError.failure("checksum mismatch unexpectedly succeeded")
        } catch is HostError {
            // Expected.
        }
    }
}

func payeeGID(
    for transactionGID: String,
    in container: NSPersistentContainer
) throws -> String? {
    let context = container.viewContext
    context.refreshAllObjects()
    let transaction = try fetchExactObject(
        entityName: "WithdrawTransaction",
        gid: transactionGID,
        context: context
    )
    let payee = transaction.value(forKey: "payee") as? NSManagedObject
    return payee?.value(forKey: "GID") as? String
}

func testSameUserAssignment() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one"],
        transactions: [("transaction-one", "user-one")],
        payees: [("payee-one", "user-one")]
    )

    let result = try writePlan(
        plan([operation(transactionGID: "transaction-one", payeeGID: "payee-one")]),
        container: container
    )
    let assignedPayeeGID = try payeeGID(for: "transaction-one", in: container)

    try require(result.reassignedTransactions == 1, "same-user assignment was not counted")
    try require(
        assignedPayeeGID == "payee-one",
        "same-user payee was not assigned"
    )
}

func testCrossUserAssignmentRejected() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one", "user-two"],
        transactions: [("transaction-one", "user-one")],
        payees: [("payee-two", "user-two")]
    )

    do {
        _ = try writePlan(
            plan([operation(transactionGID: "transaction-one", payeeGID: "payee-two")]),
            container: container
        )
        throw OwnershipTestError.failure("cross-user assignment unexpectedly succeeded")
    } catch let error as HostError {
        try require(
            error.localizedDescription.contains("must belong to the same user"),
            "cross-user assignment returned the wrong error"
        )
    }
    let assignedPayeeGID = try payeeGID(for: "transaction-one", in: container)
    try require(
        assignedPayeeGID == nil,
        "cross-user assignment changed the transaction"
    )
}

func testMixedUserPlanRejectedBeforeMutation() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one", "user-two"],
        transactions: [
            ("transaction-one", "user-one"),
            ("transaction-two", "user-two"),
        ],
        payees: [("payee-one", "user-one")]
    )

    do {
        _ = try writePlan(
            plan([
                operation(transactionGID: "transaction-one", payeeGID: "payee-one"),
                operation(transactionGID: "transaction-two", payeeGID: "payee-one"),
            ]),
            container: container
        )
        throw OwnershipTestError.failure("mixed-user plan unexpectedly succeeded")
    } catch is HostError {
        // Expected: full-plan ownership preflight rejects before assignment.
    }
    let firstAssignedPayeeGID = try payeeGID(for: "transaction-one", in: container)
    let secondAssignedPayeeGID = try payeeGID(for: "transaction-two", in: container)
    try require(
        firstAssignedPayeeGID == nil,
        "mixed-user plan changed its valid prefix before rejection"
    )
    try require(
        secondAssignedPayeeGID == nil,
        "mixed-user plan changed the mismatched transaction"
    )
}

func testEntityMismatchRejectedWithoutMutation() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one"],
        transactions: [("transaction-one", "user-one")],
        payees: [("payee-one", "user-one")]
    )

    do {
        _ = try writePlan(
            plan([
                operation(
                    transactionGID: "transaction-one",
                    entity: "DepositTransaction",
                    payeeGID: "payee-one"
                )
            ]),
            container: container
        )
        throw OwnershipTestError.failure("transaction entity mismatch unexpectedly succeeded")
    } catch is HostError {
        // Expected: exact-entity fetch excludes sibling transaction entities.
    }
    let assignedPayeeGID = try payeeGID(for: "transaction-one", in: container)
    try require(
        assignedPayeeGID == nil,
        "entity mismatch changed the transaction"
    )
}

func testLateInvalidReferenceRejectedBeforeAnyMutation() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one"],
        transactions: [
            ("transaction-one", "user-one"),
            ("transaction-two", "user-one"),
        ],
        payees: [("payee-one", "user-one")]
    )

    do {
        _ = try writePlan(
            plan([
                operation(transactionGID: "transaction-one", payeeGID: "payee-one"),
                operation(transactionGID: "transaction-two", payeeGID: "missing-payee"),
            ]),
            container: container
        )
        throw OwnershipTestError.failure("late invalid payee unexpectedly succeeded")
    } catch is HostError {
        // Expected after resolving the full plan and before any relationship set.
    }
    let firstPayeeGID = try payeeGID(for: "transaction-one", in: container)
    let secondPayeeGID = try payeeGID(for: "transaction-two", in: container)
    try require(
        firstPayeeGID == nil,
        "late invalid operation allowed an earlier assignment"
    )
    try require(
        secondPayeeGID == nil,
        "late invalid operation changed its transaction"
    )
}

func testCoreDataPreflightIsReadOnlyOnLateInvalidReference() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one"],
        transactions: [
            ("transaction-one", "user-one"),
            ("transaction-two", "user-one"),
        ],
        payees: [("payee-one", "user-one")]
    )
    let context = container.newBackgroundContext()
    var rejected = false
    var insertedCount = -1
    var updatedCount = -1
    context.performAndWait {
        do {
            _ = try preflightOperations(
                [
                    operation(transactionGID: "transaction-one", payeeGID: "payee-one"),
                    operation(transactionGID: "transaction-two", payeeGID: "missing-payee"),
                ],
                context: context
            )
        } catch is HostError {
            rejected = true
        } catch {
            // A non-host error still fails the assertion below.
        }
        insertedCount = context.insertedObjects.count
        updatedCount = context.updatedObjects.count
    }

    try require(rejected, "late invalid Core Data reference unexpectedly preflighted")
    try require(insertedCount == 0, "Core Data preflight inserted an object")
    try require(updatedCount == 0, "Core Data preflight changed an object")
}

func testNewPayeeKeyCannotCrossOwners() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one", "user-two"],
        transactions: [
            ("transaction-one", "user-one"),
            ("transaction-two", "user-two"),
        ],
        payees: []
    )

    do {
        _ = try writePlan(
            plan([
                newPayeeOperation(transactionGID: "transaction-one", key: "shared", name: "Shop"),
                newPayeeOperation(transactionGID: "transaction-two", key: "shared", name: "Shop"),
            ]),
            container: container
        )
        throw OwnershipTestError.failure("cross-owner new payee key unexpectedly succeeded")
    } catch is HostError {
        // Expected during the read-only Core Data preflight.
    }
    let firstPayeeGID = try payeeGID(for: "transaction-one", in: container)
    let secondPayeeGID = try payeeGID(for: "transaction-two", in: container)
    try require(
        firstPayeeGID == nil,
        "cross-owner key inserted or assigned a payee before rejection"
    )
    try require(
        secondPayeeGID == nil,
        "cross-owner key changed its later transaction"
    )
}

func testStableNewPayeeKeyCreatesOnceForOneOwner() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one"],
        transactions: [
            ("transaction-one", "user-one"),
            ("transaction-two", "user-one"),
        ],
        payees: []
    )

    let result = try writePlan(
        plan([
            newPayeeOperation(transactionGID: "transaction-one", key: "shared", name: "Shop"),
            newPayeeOperation(transactionGID: "transaction-two", key: "shared", name: "Shop"),
        ]),
        container: container
    )
    let firstPayeeGID = try payeeGID(for: "transaction-one", in: container)
    let secondPayeeGID = try payeeGID(for: "transaction-two", in: container)
    try require(result.createdPayees == 1, "stable new-payee key created more than one payee")
    try require(result.reassignedTransactions == 2, "new-payee assignments were not counted")
    try require(firstPayeeGID != nil, "new payee was not assigned")
    try require(firstPayeeGID == secondPayeeGID, "stable new-payee key did not reuse one payee")
}

func testWritePlanRejectsMixedMergePayloadWithoutMutation() throws {
    let container = try makeContainer()
    try seed(
        container,
        users: ["user-one"],
        transactions: [("transaction-one", "user-one")],
        payees: [("payee-one", "user-one")]
    )
    let mixedPlan = WriterPlan(
        contractVersion: 1,
        profileID: "moneywiz-2026-model-48",
        modelChecksum: "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        capability: "write.reassign-payees-by-id",
        schemaVersion: 1,
        operations: [
            operation(transactionGID: "transaction-one", payeeGID: "payee-one")
        ],
        payeeMerges: [
            PayeeMerge(sourcePayeeGID: "payee-source", targetPayeeGID: "payee-one")
        ]
    )

    do {
        _ = try writePlan(mixedPlan, container: container)
        throw OwnershipTestError.failure("mixed merge payload unexpectedly succeeded")
    } catch is HostError {
        // Expected before the context can mutate the transaction.
    }
    let assignedPayeeGID = try payeeGID(for: "transaction-one", in: container)
    try require(
        assignedPayeeGID == nil,
        "rejected mixed merge payload changed the transaction"
    )
}

func testReadOnlyModelChecksumWithoutStore() throws {
    let directory = FileManager.default.temporaryDirectory
        .appendingPathComponent("moneywiz-model-inspection-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: directory) }
    let model = makeModel()
    let modelURL = directory.appendingPathComponent("synthetic.mom")
    let archived = try NSKeyedArchiver.archivedData(withRootObject: model, requiringSecureCoding: false)
    try archived.write(to: modelURL)
    let coordinator = NSPersistentStoreCoordinator(managedObjectModel: model)
    let observed = try readModelChecksum(at: modelURL)
    try require(observed == coordinator.managedObjectModel.versionChecksum, "model inspection checksum differs")
    try require(coordinator.persistentStores.isEmpty, "inspection opened a persistent store")
    let contents = try FileManager.default.contentsOfDirectory(atPath: directory.path)
    try require(contents == ["synthetic.mom"], "inspection created unexpected artifacts")
    do {
        _ = try readModelChecksum(at: directory.appendingPathComponent("missing.mom"))
        throw OwnershipTestError.failure("missing model was accepted")
    } catch is HostError {
        // Missing models must fail without creating anything.
    }
}

func ownerURI(for transactionGID: String, in container: NSPersistentContainer) throws -> String {
    let transaction = try fetchExactObject(
        entityName: "WithdrawTransaction", gid: transactionGID, context: container.viewContext
    )
    guard let account = transaction.value(forKey: "account") as? NSManagedObject,
          let owner = account.value(forKey: "user") as? NSManagedObject else {
        throw OwnershipTestError.failure("synthetic transaction lacks an owner")
    }
    return owner.objectID.uriRepresentation().absoluteString
}

func v2Payload(ownerURI: String, expectedOldPayeeGID: String?) throws -> (WriterPlanV2, [String: Any]) {
    let operation: [String: Any] = [
        "operation_id": "operation-one",
        "kind": "reassign_payee",
        "capability": "write.reassign-payees-by-id",
        "transaction_entity": "WithdrawTransaction",
        "transaction_gid": "transaction-one",
        "expected_old_payee_gid": expectedOldPayeeGID ?? NSNull(),
        "target_payee_gid": "payee-one",
        "owner_uri": ownerURI,
        "source_event_id": "source-event-one",
        "expected_postcondition": ["payee_gid": "payee-one"],
        "allowed_changed_fields": ["payee"],
    ]
    var raw: [String: Any] = [
        "contract_version": 2,
        "operation_schema_version": 1,
        "plan_id": "plan-one",
        "profile_id": "moneywiz-2026-model-48",
        "model_checksum": "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
        "store_identity": ["store_uuid": "synthetic-store"],
        "owner_uri": ownerURI,
        "app_identity": [
            "bundle_id": "com.moneywiz.personalfinance", "version": "0.3.0",
            "path": "/synthetic/MoneyWiz.app", "model_path": "/synthetic/MoneyWiz.app/model.mom",
        ],
        "capability": "write.reassign-payees-by-id",
        "created_at": "2026-09-13T00:00:00Z",
        "timezone": "Europe/Rome",
        "source_interval": ["start": "2026-09-01T00:00:00Z", "end": "2026-09-13T00:00:00Z"],
        "source_evidence_refs": ["private:source-one"],
        "expected_account_gid": "account-user-one",
        "expected_cached_account_balance": "0.00",
        "currency_unit": "EUR",
        "source_event_id": "source-event-one",
        "operations": [operation],
    ]
    raw["plan_digest"] = try canonicalV2Digest(raw)
    let data = try JSONSerialization.data(withJSONObject: raw, options: [])
    return (try JSONDecoder().decode(WriterPlanV2.self, from: data), raw)
}

func testV2BridgeValidatesDigestAndRejectsFutureOperations() throws {
    let container = try makeContainer()
    try seed(container, users: ["user-one"], transactions: [("transaction-one", "user-one")], payees: [("payee-one", "user-one")])
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (valid, raw) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    try validateWriterPlanV2(valid, rawPlan: raw)

    var altered = raw
    altered["capability"] = "write.create-transaction"
    let alteredData = try JSONSerialization.data(withJSONObject: altered, options: [])
    let candidate = try JSONDecoder().decode(WriterPlanV2.self, from: alteredData)
    do {
        try validateWriterPlanV2(candidate, rawPlan: altered)
        throw OwnershipTestError.failure("future operation capability unexpectedly succeeded")
    } catch is HostError {
        // A digest cannot promote an unverified operation kind or capability.
    }
}

func testV2BridgeAtomicallyAppliesAndRecoversAsNoop() throws {
    let container = try makeContainer()
    try seed(container, users: ["user-one"], transactions: [("transaction-one", "user-one")], payees: [("payee-one", "user-one")])
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (planV2, _) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    let applied = try writePlanV2(planV2, container: container, requireStopped: {})
    try require(applied.classification == "applied" && applied.verified, "v2 bridge did not verify write")
    try require(applied.operations.first?.status == "applied", "v2 bridge did not report per-operation result")
    let persistedPayee = try payeeGID(for: "transaction-one", in: container)
    try require(persistedPayee == "payee-one", "v2 bridge did not persist target payee")

    let recovered = try writePlanV2(planV2, container: container, requireStopped: {})
    try require(recovered.classification == "noop", "post-save recovery did not classify as noop")
    try require(recovered.operations.first?.status == "noop", "post-save recovery did not return noop status")
}

func testV2BridgeRefusesMixedRecoveryBeforeMutation() throws {
    let container = try makeContainer()
    try seed(
        container, users: ["user-one"], transactions: [("transaction-one", "user-one")],
        payees: [("payee-one", "user-one"), ("other-payee", "user-one")]
    )
    let context = container.viewContext
    let transaction = try fetchExactObject(entityName: "WithdrawTransaction", gid: "transaction-one", context: context)
    let other = try fetchExactObject(entityName: "Payee", gid: "other-payee", context: context)
    transaction.setValue(other, forKey: "payee")
    try context.save()
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (planV2, _) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    do {
        _ = try writePlanV2(planV2, container: container, requireStopped: {})
        throw OwnershipTestError.failure("mixed v2 recovery state unexpectedly replayed")
    } catch let error as HostError {
        try require(error.localizedDescription.contains("mixed or unknown"), "mixed recovery returned wrong error")
    }
    let finalPayee = try payeeGID(for: "transaction-one", in: container)
    try require(finalPayee == "other-payee", "mixed recovery changed data")
}

func testV2BridgeSecondAppCheckRollsBackBeforeSave() throws {
    let container = try makeContainer()
    try seed(container, users: ["user-one"], transactions: [("transaction-one", "user-one")], payees: [("payee-one", "user-one")])
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (planV2, _) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    var checks = 0
    do {
        _ = try writePlanV2(planV2, container: container, requireStopped: {
            checks += 1
            if checks == 2 { throw HostError.message("MoneyWiz reopened") }
        })
        throw OwnershipTestError.failure("second app check unexpectedly saved")
    } catch is HostError {
        // Expected: complete preflight succeeds but save is refused before mutation.
    }
    let finalPayee = try payeeGID(for: "transaction-one", in: container)
    try require(checks == 2, "v2 bridge did not recheck app state before save")
    try require(finalPayee == nil, "second app check left a partial write")
}

func runSQLiteCrashProbe(storePath: String, point: WriterTestCrashPoint) throws {
    let url = URL(fileURLWithPath: storePath)
    let container = try makeSQLiteContainer(at: url)
    try seed(
        container, users: ["user-one"], transactions: [("transaction-one", "user-one")],
        payees: [("payee-one", "user-one")]
    )
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (planV2, _) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    writerTestCrashPoint = point
    _ = try writePlanV2(planV2, container: container, requireStopped: {})
}

func runSQLiteRecoveryProbe(storePath: String) throws {
    let container = try makeSQLiteContainer(at: URL(fileURLWithPath: storePath))
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (planV2, _) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    let result = try recoverPlanV2(planV2, container: container)
    print(result.classification)
}

func testV2RecoveryRefusesForeignTargetOwner() throws {
    let container = try makeContainer()
    try seed(container, users: ["user-one", "user-two"], transactions: [("transaction-one", "user-one")], payees: [("payee-one", "user-two")])
    let transaction = try fetchExactObject(entityName: "WithdrawTransaction", gid: "transaction-one", context: container.viewContext)
    let foreign = try fetchExactObject(entityName: "Payee", gid: "payee-one", context: container.viewContext)
    transaction.setValue(foreign, forKey: "payee")
    try container.viewContext.save()
    let owner = try ownerURI(for: "transaction-one", in: container)
    let (plan, _) = try v2Payload(ownerURI: owner, expectedOldPayeeGID: nil)
    do {
        _ = try recoverPlanV2(plan, container: container)
        throw OwnershipTestError.failure("recovery verified a foreign payee owner")
    } catch is HostError { }
}

@main
struct MoneyWizToolsHostOwnershipTests {
    static func main() throws {
        let args = Array(CommandLine.arguments.dropFirst())
        if args.count == 2, args[0] == "--crash-before-save" {
            try runSQLiteCrashProbe(storePath: args[1], point: .beforeSave)
            return
        }
        if args.count == 2, args[0] == "--crash-after-save" {
            try runSQLiteCrashProbe(storePath: args[1], point: .afterSave)
            return
        }
        if args.count == 2, args[0] == "--recover" {
            try runSQLiteRecoveryProbe(storePath: args[1])
            return
        }
        try testReadOnlyModelChecksumWithoutStore()
        try testWriterContractRequiresExactProfileAndChecksum()
        try testWriterPolicyAcceptsExactlyTenTransactionEntities()
        try testWriterContractRejectsPartialMixedAndAmbiguousOperations()
        try testWriterContractRejectsBlockedAndMixedPlanShapes()
        try testMoneyWizProcessInspectionFailsClosed()
        try testStoreAndSelectedModelChecksumsMustBothMatch()
        try testSameUserAssignment()
        try testCrossUserAssignmentRejected()
        try testMixedUserPlanRejectedBeforeMutation()
        try testEntityMismatchRejectedWithoutMutation()
        try testLateInvalidReferenceRejectedBeforeAnyMutation()
        try testCoreDataPreflightIsReadOnlyOnLateInvalidReference()
        try testNewPayeeKeyCannotCrossOwners()
        try testStableNewPayeeKeyCreatesOnceForOneOwner()
        try testWritePlanRejectsMixedMergePayloadWithoutMutation()
        try testV2BridgeValidatesDigestAndRejectsFutureOperations()
        try testV2BridgeAtomicallyAppliesAndRecoversAsNoop()
        try testV2BridgeRefusesMixedRecoveryBeforeMutation()
        try testV2BridgeSecondAppCheckRollsBackBeforeSave()
        try testV2RecoveryRefusesForeignTargetOwner()
        print("MoneyWiz Tools host ownership tests passed")
    }
}
