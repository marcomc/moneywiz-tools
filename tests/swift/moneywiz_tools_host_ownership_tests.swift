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
        profileID: "ownership-test",
        schemaVersion: 1,
        operations: operations,
        payeeMerges: nil
    )
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

@main
struct MoneyWizToolsHostOwnershipTests {
    static func main() throws {
        try testSameUserAssignment()
        try testCrossUserAssignmentRejected()
        try testMixedUserPlanRollsBack()
        print("MoneyWiz Tools host ownership tests passed")
    }
}
