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

func dateAttribute(_ name: String) -> NSAttributeDescription {
    let attribute = NSAttributeDescription()
    attribute.name = name
    attribute.attributeType = .dateAttributeType
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

    account.properties = [toOneRelationship("user", destination: user)]
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

@main
struct MoneyWizToolsHostOwnershipTests {
    static func main() throws {
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
        print("MoneyWiz Tools host ownership tests passed")
    }
}
