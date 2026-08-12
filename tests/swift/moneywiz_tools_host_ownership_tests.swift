import CoreData
import Foundation

enum OwnershipTestError: Error {
    case failure(String)
}

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

    let transaction = NSEntityDescription()
    transaction.name = "WithdrawTransaction"
    transaction.managedObjectClassName = "NSManagedObject"

    account.properties = [toOneRelationship("user", destination: user)]
    payee.properties = [
        stringAttribute("GID"),
        toOneRelationship("user", destination: user),
    ]
    transaction.properties = [
        stringAttribute("GID"),
        toOneRelationship("account", destination: account),
        toOneRelationship("payee", destination: payee, optional: true),
    ]

    let model = NSManagedObjectModel()
    model.entities = [user, account, payee, transaction]
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
        account.setValue(userObjects[userID], forKey: "user")
        accounts[userID] = account
    }

    for payeeSeed in payees {
        let payee = NSEntityDescription.insertNewObject(
            forEntityName: "Payee",
            into: context
        )
        payee.setValue(payeeSeed.gid, forKey: "GID")
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
    let transaction = try fetchObject(
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

func testMixedUserPlanRollsBack() throws {
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
        // Expected: the writer rolls back the earlier valid assignment too.
    }
    let firstAssignedPayeeGID = try payeeGID(for: "transaction-one", in: container)
    let secondAssignedPayeeGID = try payeeGID(for: "transaction-two", in: container)
    try require(
        firstAssignedPayeeGID == nil,
        "mixed-user plan did not roll back its valid prefix"
    )
    try require(
        secondAssignedPayeeGID == nil,
        "mixed-user plan changed the mismatched transaction"
    )
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

@main
struct MoneyWizToolsHostOwnershipTests {
    static func main() throws {
        try testWriterContractRequiresExactProfileAndChecksum()
        try testWriterContractRejectsBlockedAndMixedPlanShapes()
        try testMoneyWizProcessInspectionFailsClosed()
        try testStoreAndSelectedModelChecksumsMustBothMatch()
        try testSameUserAssignment()
        try testCrossUserAssignmentRejected()
        try testMixedUserPlanRollsBack()
        try testWritePlanRejectsMixedMergePayloadWithoutMutation()
        print("MoneyWiz Tools host ownership tests passed")
    }
}
