import CoreData
import Foundation

func fixtureObject(_ entity: String, _ context: NSManagedObjectContext) throws -> NSManagedObject {
    guard let description = NSEntityDescription.entity(forEntityName: entity, in: context) else {
        throw HostError.message("W01 fixture model lacks \(entity)")
    }
    return NSManagedObject(entity: description, insertInto: context)
}

func fixtureSet(_ object: NSManagedObject, _ key: String, _ value: Any?) throws {
    guard object.entity.propertiesByName[key] != nil else { throw HostError.message("W01 fixture lacks \(key)") }
    object.setValue(value, forKey: key)
}

func fixtureAccount(_ entity: String, gid: String, name: String, opening: Double,
                    balance: Double, user: NSManagedObject,
                    context: NSManagedObjectContext) throws -> NSManagedObject {
    let account = try fixtureObject(entity, context)
    try fixtureSet(account, "GID", gid); try fixtureSet(account, "name", name)
    try fixtureSet(account, "objectCreationDate", Date()); try fixtureSet(account, "openingBalance", opening)
    try fixtureSet(account, "ballance", balance); try fixtureSet(account, "currencyName", "EUR")
    try fixtureSet(account, "user", user)
    return account
}

func fixtureWithdrawal(_ gid: String, account: NSManagedObject,
                       context: NSManagedObjectContext) throws -> NSManagedObject {
    let original = try fixtureObject("WithdrawTransaction", context)
    try fixtureSet(original,"GID",gid); try fixtureSet(original,"amount",-10.0); try fixtureSet(original,"originalAmount",-10.0); try fixtureSet(original,"originalCurrency","EUR"); try fixtureSet(original,"originalExchangeRate",1.0); try fixtureSet(original,"objectCreationDate",Date()); try fixtureSet(original,"reconciled",false); try fixtureSet(original,"flags",0); try fixtureSet(original,"date",ISO8601DateFormatter().date(from:"2026-09-10T00:00:00Z")!); try fixtureSet(original,"status",1); try fixtureSet(original,"voidCheque",0); try fixtureSet(original,"account",account)
    return original
}

func fixtureTransaction(_ entity: String, gid: String, amount: Double,
                        account: NSManagedObject, payee: NSManagedObject,
                        tag: NSManagedObject, context: NSManagedObjectContext) throws -> NSManagedObject {
    let transaction = try fixtureObject(entity, context)
    try fixtureSet(transaction, "GID", gid)
    try fixtureSet(transaction, "amount", amount)
    try fixtureSet(transaction, "originalAmount", amount)
    try fixtureSet(transaction, "originalCurrency", "EUR")
    try fixtureSet(transaction, "originalExchangeRate", 1.0)
    try fixtureSet(transaction, "objectCreationDate", ISO8601DateFormatter().date(from: "2026-09-09T08:00:00Z")!)
    try fixtureSet(transaction, "date", ISO8601DateFormatter().date(from: "2026-09-10T09:30:00Z")!)
    try fixtureSet(transaction, "notes", "W02 original note")
    try fixtureSet(transaction, "desc", "W02 original description")
    try fixtureSet(transaction, "checkbookNumber", "W02-001")
    try fixtureSet(transaction, "reconciled", false)
    try fixtureSet(transaction, "flags", 0)
    try fixtureSet(transaction, "status", 1)
    try fixtureSet(transaction, "voidCheque", 0)
    try fixtureSet(transaction, "account", account)
    try fixtureSet(transaction, "payee", payee)
    try fixtureSet(transaction, "tags", NSSet(object: tag))
    return transaction
}

func fixtureCategoryAssignment(_ transaction: NSManagedObject, category: NSManagedObject,
                               amount: Double, context: NSManagedObjectContext) throws {
    let assignment = try fixtureObject("CategoryAssigment", context)
    try fixtureSet(assignment, "amount", amount)
    try fixtureSet(assignment, "assigmentNumber", 0)
    try fixtureSet(assignment, "category", category)
    try fixtureSet(assignment, "transaction", transaction)
}

func fixtureRefundLink(_ withdrawal: NSManagedObject, refund: NSManagedObject,
                       context: NSManagedObjectContext) throws {
    let link = try fixtureObject("WithdrawRefundTransactionLink", context)
    try fixtureSet(link, "withdrawTransaction", withdrawal)
    try fixtureSet(link, "refundTransaction", refund)
}

func fixtureSupportedDeletion(_ user: NSManagedObject, foreignUser: NSManagedObject,
                              context: NSManagedObjectContext) throws {
    let environment = ProcessInfo.processInfo.environment
    let accountEntity = environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] ?? "BankChequeAccount"
    guard supportedAccountEntities.contains(accountEntity) else { throw HostError.message("W06 unsupported fixture account") }
    let currency = environment["MONEYWIZ_TEST_CURRENCY"] ?? "EUR"
    let investmentEntity = environment["MONEYWIZ_TEST_INVESTMENT_ENTITY"] ?? "InvestmentAccount"
    guard ["InvestmentAccount", "ForexAccount"].contains(investmentEntity) else { throw HostError.message("W06 unsupported fixture investment account") }
    let account = try fixtureAccount(accountEntity, gid: "w06-account", name: "W06 ordinary",
        opening: 100, balance: 0, user: user, context: context)
    let recipient = try fixtureAccount("BankSavingAccount", gid: "w06-recipient", name: "W06 recipient",
        opening: 50, balance: 0, user: user, context: context)
    let investment = try fixtureAccount(investmentEntity, gid: "w06-investment", name: "W06 investment",
        opening: 100, balance: 0, user: user, context: context)
    for object in [account, recipient, investment] { try fixtureSet(object, "currencyName", currency) }
    let foreign = try fixtureAccount("CashAccount", gid: "w06-foreign", name: "W06 foreign",
        opening: 0, balance: 0, user: foreignUser, context: context)
    let payee = try fixtureObject("Payee", context)
    try fixtureSet(payee, "GID", "w06-payee"); try fixtureSet(payee, "name", "W06 shared")
    try fixtureSet(payee, "user", user)
    let tag = try fixtureObject("Tag", context)
    try fixtureSet(tag, "GID", "w06-tag"); try fixtureSet(tag, "name", "W06 shared")
    try fixtureSet(tag, "user", user)
    let category = try fixtureObject("Category", context)
    try fixtureSet(category, "GID", "w06-category"); try fixtureSet(category, "name", "W06 shared")
    try fixtureSet(category, "type", 1); try fixtureSet(category, "user", user)
    func row(_ entity: String, _ gid: String, _ amount: Double, _ ownerAccount: NSManagedObject) throws -> NSManagedObject {
        let object = try fixtureTransaction(entity, gid: gid, amount: amount, account: ownerAccount,
            payee: payee, tag: tag, context: context)
        try fixtureSet(object, "originalCurrency", currency)
        return object
    }
    let expense = try row("WithdrawTransaction", "w06-expense", -10, account)
    try fixtureCategoryAssignment(expense, category: category, amount: -10, context: context)
    let firstRefund = try row("RefundTransaction", "w06-refund-1", 2, account)
    let secondRefund = try row("RefundTransaction", "w06-refund-2", 3, account)
    try fixtureRefundLink(expense, refund: firstRefund, context: context)
    try fixtureRefundLink(expense, refund: secondRefund, context: context)
    _ = try row("DepositTransaction", "w06-income", 4, account)
    let categorized = try row("WithdrawTransaction", "w06-categorized", -4, account)
    try fixtureCategoryAssignment(categorized, category: category, amount: -4, context: context)
    let adjustment = try row("ReconcileTransaction", "w06-adjustment", 1, account)
    try fixtureSet(adjustment, "reconcileAmount", 96.0)
    let sender = try row("TransferWithdrawTransaction", "w06-send", -5, account)
    let receiver = try row("TransferDepositTransaction", "w06-receive", 5, recipient)
    try fixtureSet(sender, "recipientTransaction", receiver)
    try fixtureSet(sender, "recipientAccount", recipient)
    try fixtureSet(receiver, "senderAccount", account)
    let holding = try fixtureObject("InvestmentHolding", context)
    let symbol = investmentEntity == "ForexAccount" ? "USD" : "W06"
    try fixtureSet(holding, "GID", "w06-holding"); try fixtureSet(holding, "symbol", symbol)
    try fixtureSet(holding, "investmentAccount", investment)
    try fixtureSet(holding, "investmentObjectType", investmentEntity == "ForexAccount" ? 1 : 0)
    try fixtureSet(holding, "openningNumberOfShares", 3.0)
    try fixtureSet(holding, "pricePerShare", 10.0)
    if let prices = environment["MONEYWIZ_TEST_HISTORICAL_PRICES"] {
        let history = NSMutableDictionary()
        let early = Date(timeIntervalSinceReferenceDate: 123456789.25)
        let late = Date(timeIntervalSinceReferenceDate: 123456790.75)
        if prices == "numeric-key" {
            history[NSNumber(value: 1)] = NSNumber(value: 10)
        } else {
            for date in prices == "reverse" ? [late, early] : [early, late] {
                history[date] = NSNumber(value: date == early ? 10.5 : 11.25)
            }
            if prices == "string-price" { history[early] = "10.5" }
            if prices == "bool-price" { history[early] = NSNumber(value: true) }
            if prices == "infinite-price" { history[early] = NSNumber(value: Double.infinity) }
        }
        try fixtureSet(holding, "manualHistoricalPricesPerShare", history)
    }
    let buy = try row("InvestmentBuyTransaction", "w06-buy", -20, investment)
    try fixtureSet(buy, "investmentHolding", holding); try fixtureSet(buy, "symbol", symbol)
    try fixtureSet(buy, "numberOfShares", 2.0); try fixtureSet(buy, "pricePerShare", 10.0)
    let sell = try row("InvestmentSellTransaction", "w06-sell", 40, investment)
    try fixtureSet(sell, "investmentHolding", holding); try fixtureSet(sell, "symbol", symbol)
    try fixtureSet(sell, "numberOfShares", 4.0); try fixtureSet(sell, "pricePerShare", 10.0)
    if environment["MONEYWIZ_TEST_QUANTITY_ADJUSTMENT"] == "1" {
        let quantity = try row("ReconcileTransaction", "w06-quantity", 0, investment)
        try fixtureSet(quantity, "investmentHolding", holding); try fixtureSet(quantity, "symbol", symbol)
        try fixtureSet(quantity, "numberOfShares", 0.5)
        try fixtureSet(quantity, "reconcileNumberOfShares", 1.5)
    }
    _ = try row("DepositTransaction", "w06-foreign-income", 1, foreign)
}

func fixtureJSONValue(_ value: Any?) -> Any {
    guard let value else { return NSNull() }
    if let date = value as? Date {
        return ISO8601DateFormatter().string(from: date)
    }
    if value is String || value is NSNumber || value is NSNull { return value }
    return String(describing: value)
}

func fixtureRelationshipIDs(_ transaction: NSManagedObject, _ key: String) throws -> [String] {
    guard let relationship = transaction.entity.relationshipsByName[key] else {
        throw HostError.message("W02 fixture lacks relationship \(key)")
    }
    if relationship.isToMany {
        return try relatedObjects(transaction, key).map {
            $0.objectID.uriRepresentation().absoluteString
        }.sorted()
    }
    return (transaction.value(forKey: key) as? NSManagedObject).map {
        [$0.objectID.uriRepresentation().absoluteString]
    } ?? []
}

func runFixtureInspection(_ args: [String]) throws {
    guard args.count == 9, args[0] == "--inspect", args[1] == "--store",
          args[3] == "--model", args[5] == "--entity", args[7] == "--gid" else {
        throw HostError.message("invalid W02 inspection arguments")
    }
    let store = URL(fileURLWithPath: args[2])
    let modelURL = URL(fileURLWithPath: args[4])
    guard let model = NSManagedObjectModel(contentsOf: modelURL) else {
        throw HostError.message("invalid W02 inspection model")
    }
    configureTransformers()
    let container = NSPersistentContainer(name: "W02Inspection", managedObjectModel: model)
    let description = NSPersistentStoreDescription(url: store)
    description.isReadOnly = true
    description.shouldAddStoreAsynchronously = false
    description.shouldMigrateStoreAutomatically = false
    description.shouldInferMappingModelAutomatically = false
    container.persistentStoreDescriptions = [description]
    var loadError: Error?
    container.loadPersistentStores { _, value in loadError = value }
    if let loadError { throw loadError }
    let context = container.viewContext
    let transaction = try fetchExactObject(entityName: args[6], gid: args[8], context: context)
    var attributes: [String: Any] = [:]
    for key in transaction.entity.attributesByName.keys.sorted() {
        attributes[key] = fixtureJSONValue(transaction.value(forKey: key))
    }
    var relationships: [String: [String]] = [:]
    for key in transaction.entity.relationshipsByName.keys.sorted() {
        relationships[key] = try fixtureRelationshipIDs(transaction, key)
    }
    let account = supportedAccountEntities.contains(transaction.entity.name ?? "")
        ? transaction : transaction.value(forKey: transaction.entity.name == "InvestmentHolding"
            ? "investmentAccount" : "account") as? NSManagedObject
    let result: [String: Any] = [
        "entity": transaction.entity.name ?? "",
        "object_uri": transaction.objectID.uriRepresentation().absoluteString,
        "attributes": attributes,
        "relationships": relationships,
        "account_balance": fixtureJSONValue(account?.value(forKey: "ballance")),
    ]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

func runFixturePayeeInspection(_ args: [String]) throws {
    guard args.count == 5, args[0] == "--inspect-w09", args[1] == "--store",
          args[3] == "--model" else {
        throw HostError.message("invalid W09 inspection arguments")
    }
    configureTransformers()
    let container = try loadContainer(
        storeURL: URL(fileURLWithPath: args[2]),
        modelURL: URL(fileURLWithPath: args[4]),
        expectedChecksum: "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=", readOnly: true
    )
    let context = container.viewContext
    let source = try optionalPayee(gid: "w09-source", context: context)
    let survivor = try fetchExactObject(entityName: "Payee", gid: "w09-survivor", context: context)
    let unrelated = try fetchExactObject(entityName: "Payee", gid: "w09-unrelated", context: context)
    var references: [String: [String]] = [:]
    for relationship in ["transactions", "stringHistoryItems", "scheduledTransactions",
                         "connectedPaymentPlans", "infoCards"] {
        guard let objects = survivor.value(forKey: relationship) as? NSSet else {
            throw HostError.message("W09 survivor relationship is incomplete")
        }
        references[relationship] = objects.compactMap { ($0 as? NSManagedObject)?
            .objectID.uriRepresentation().absoluteString }.sorted()
    }
    let card = (survivor.value(forKey: "infoCards") as? NSSet)?.allObjects
        .compactMap { $0 as? NSManagedObject }.first
    let cardPayees = (card?.value(forKey: "payees") as? NSSet)?.compactMap {
        ($0 as? NSManagedObject)?.value(forKey: "GID") as? String
    }.sorted() ?? []
    let result: [String: Any] = [
        "source_absent": source == nil,
        "survivor_references": references,
        "card_payees": cardPayees,
        "unrelated_name": unrelated.value(forKey: "name") as? String ?? "",
    ]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result,
                                                                   options: [.sortedKeys]))
    FileHandle.standardOutput.write(Data([10]))
}

func runFixtureCrash(_ args: [String]) throws -> Never {
    guard args.count == 7,
          ["--crash-before-save", "--crash-after-save"].contains(args[0]),
          args[1] == "--store", args[3] == "--model", args[5] == "--plan" else {
        throw HostError.message("invalid W01 crash fixture arguments")
    }
    let store = URL(fileURLWithPath: args[2])
    let model = URL(fileURLWithPath: args[4])
    let data = try Data(contentsOf: URL(fileURLWithPath: args[6]))
    let raw = try JSONSerialization.jsonObject(with: data) as! [String: Any]
    if let capability = raw["capability"] as? String, capability.hasPrefix("write.merge-") {
        let plan = try JSONDecoder().decode(PayeeMergePlanV2.self, from: data)
        try validatePayeeMergePlanV2(plan, raw: raw)
        let container = try loadContainer(storeURL: store, modelURL: model,
                                          expectedChecksum: plan.modelChecksum)
        writerTestCrashPoint = args[0] == "--crash-before-save" ? .beforeSave : .afterSave
        _ = try writePayeeMergeV2(plan, container: container, requireStopped: {})
        throw HostError.message("W09 crash fixture did not stop at the requested boundary")
    }
    let plan = try JSONDecoder().decode(WriterPlanV2.self, from: data)
    try validateWriterPlanV2(plan, rawPlan: raw)
    if plan.capability == "write.delete-supported-transactions" {
        _ = try preflightSupportedDeletionAtStore(plan, storeURL: store, modelURL: model)
    }
    let container = try loadContainer(
        storeURL: store, modelURL: model,
        expectedChecksum: plan.modelChecksum
    )
    writerTestCrashPoint = args[0] == "--crash-before-save" ? .beforeSave : .afterSave
    _ = try writePlanV2(plan, container: container, requireStopped: {})
    throw HostError.message("W01 crash fixture did not stop at the requested boundary")
}

func runFixtureWriter() throws {
    let arguments = try parseWriterArguments()
    let data = try Data(contentsOf: arguments.plan)
    let raw = try JSONSerialization.jsonObject(with: data) as! [String: Any]
    if let capability = raw["capability"] as? String, capability.hasPrefix("write.merge-") {
        let plan = try JSONDecoder().decode(PayeeMergePlanV2.self, from: data)
        try validatePayeeMergePlanV2(plan, raw: raw)
        let container = try loadContainer(
            storeURL: arguments.store, modelURL: arguments.model,
            expectedChecksum: plan.modelChecksum, readOnly: arguments.recoverOnly
        )
        if !arguments.recoverOnly {
            switch ProcessInfo.processInfo.environment["MONEYWIZ_TEST_CRASH_POINT"] {
            case "before-save": writerTestCrashPoint = .beforeSave
            case "after-save": writerTestCrashPoint = .afterSave
            default: writerTestCrashPoint = nil
            }
        }
        let result = try arguments.recoverOnly
            ? recoverPayeeMergeV2(plan, container: container)
            : writePayeeMergeV2(plan, container: container, requireStopped: {})
        FileHandle.standardOutput.write(try JSONEncoder().encode(result))
        FileHandle.standardOutput.write(Data([10]))
        return
    }
    let plan = try JSONDecoder().decode(WriterPlanV2.self, from: data)
    try validateWriterPlanV2(plan, rawPlan: raw)
    if plan.capability == "write.delete-supported-transactions" && !arguments.recoverOnly,
       let noop = try preflightSupportedDeletionAtStore(plan, storeURL: arguments.store, modelURL: arguments.model) {
        FileHandle.standardOutput.write(try JSONEncoder().encode(noop))
        FileHandle.standardOutput.write(Data([10]))
        return
    }
    let container = try loadContainer(
        storeURL: arguments.store, modelURL: arguments.model,
        expectedChecksum: plan.modelChecksum,
        readOnly: arguments.recoverOnly
    )
    let result: WriterResultV2
    if arguments.recoverOnly {
        result = try recoverPlanV2(plan, container: container)
    } else {
        switch ProcessInfo.processInfo.environment["MONEYWIZ_TEST_CRASH_POINT"] {
        case "before-save": writerTestCrashPoint = .beforeSave
        case "after-save": writerTestCrashPoint = .afterSave
        default: writerTestCrashPoint = nil
        }
        result = try writePlanV2(plan, container: container, requireStopped: {})
    }
    FileHandle.standardOutput.write(try JSONEncoder().encode(result))
    FileHandle.standardOutput.write(Data([10]))
}

@main struct MoneyWizW01Fixture {
    static func main() {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            if ["--coredata-write", "--coredata-recover"].contains(args.first) {
                try runFixtureWriter()
                return
            }
            if args.first == "--inspect" {
                try runFixtureInspection(args)
                return
            }
            if args.first == "--inspect-w09" {
                try runFixturePayeeInspection(args)
                return
            }
            if args.first == "--coredata-payee-inventory" {
                let inventory = try inspectPayeeInventory(args)
                FileHandle.standardOutput.write(try JSONEncoder().encode(inventory))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            if args.first?.hasPrefix("--crash-") == true {
                try runFixtureCrash(args)
            }
            guard (args.count == 4 || args.count == 5), args[0] == "--store", args[2] == "--model",
                  args.count == 4 || ["--unmarked", "--w06", "--w06-backdated", "--w06-unmarked", "--w06-linked", "--w06-supported",
                    "--w07-source", "--w07-paired", "--w07-reverse", "--w07-ambiguous",
                    "--w07-unmarked", "--w07-voided", "--w08-aggregate",
                    "--w08-units", "--w08-unmarked", "--w05-balance", "--w05-cash", "--w05-quantity",
                    "--w05-unmarked-balance", "--w05-unmarked-cash", "--w05-unmarked-quantity", "--w09-exact",
                    "--w09-fuzzy", "--w09-untrimmed", "--w09-control-space",
                    "--w09-blank-control",
                    "--w09-unmarked"].contains(args[4]) else {
                throw HostError.message("usage")
            }
            let store = URL(fileURLWithPath: args[1]), modelURL = URL(fileURLWithPath: args[3])
            guard !FileManager.default.fileExists(atPath: store.path), let model = NSManagedObjectModel(contentsOf: modelURL) else { throw HostError.message("invalid disposable fixture inputs") }
            configureTransformers()
            let container = NSPersistentContainer(name: "W01", managedObjectModel: model)
            let description = NSPersistentStoreDescription(url: store); description.shouldAddStoreAsynchronously = false
            container.persistentStoreDescriptions = [description]
            var error: Error?; container.loadPersistentStores { _, value in error = value }; if let error { throw error }
            guard let persistentStore = container.persistentStoreCoordinator.persistentStores.first else { throw HostError.message("fixture has no persistent store") }
            if args.count == 4 || ["--w06", "--w06-backdated", "--w06-linked", "--w06-supported", "--w07-source",
                "--w07-paired", "--w07-reverse", "--w07-ambiguous",
                "--w07-voided", "--w08-aggregate", "--w08-units", "--w05-balance", "--w05-cash", "--w05-quantity",
                "--w09-exact", "--w09-fuzzy", "--w09-untrimmed",
                "--w09-control-space", "--w09-blank-control"].contains(args[4]) {
                var storeMetadata = persistentStore.metadata ?? [:]
                storeMetadata["MoneyWizToolsDisposableFixture"] = "W01-v1"
                container.persistentStoreCoordinator.setMetadata(storeMetadata, for: persistentStore)
            }
            let c = container.viewContext
            let user = try fixtureObject("User", c)
            try fixtureSet(user, "syncLogin", "w01-fixture@example.invalid")
            let foreignUser = try fixtureObject("User", c)
            try fixtureSet(foreignUser, "syncLogin", "w01-foreign@example.invalid")
            if args.count == 5 && args[4] == "--w06-supported" {
                try fixtureSupportedDeletion(user, foreignUser: foreignUser, context: c)
                try c.save()
                let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(ofType: NSSQLiteStoreType, at: store, options: nil)
                let identity = ["store_uuid": metadata[NSStoreUUIDKey] as! String,
                    "owner_uri": user.objectID.uriRepresentation().absoluteString]
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys]))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            if args.count == 5 && args[4].hasPrefix("--w05-") {
                let quantity = args[4].hasSuffix("quantity")
                let cash = args[4].hasSuffix("cash")
                let entity = ProcessInfo.processInfo.environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] ??
                    (quantity ? "ForexAccount" : cash ? "InvestmentAccount" : "BankChequeAccount")
                let account = try fixtureAccount(entity, gid: "w05-account", name: "W05 account",
                    opening: 100, balance: 0, user: user, context: c)
                try fixtureSet(account, "currencyName", ProcessInfo.processInfo.environment["MONEYWIZ_TEST_CURRENCY"] ?? "EUR")
                try fixtureSet(account, "archived", false)
                if quantity {
                    let holding = try fixtureObject("InvestmentHolding", c)
                    try fixtureSet(holding, "GID", "w05-holding")
                    try fixtureSet(holding, "symbol", "ETH")
                    try fixtureSet(holding, "investmentObjectType", entity == "InvestmentAccount" ? 0 : 1)
                    try fixtureSet(holding, "openningNumberOfShares", 1.1)
                    try fixtureSet(holding, "investmentAccount", account)
                    for (rowEntity, gid, delta) in [(entity == "InvestmentAccount" ? "InvestmentBuyTransaction" : "DepositTransaction", "w05-deposit", 0.01),
                                                 ("ReconcileTransaction", "w05-adjustment", 0.005)] {
                        let row = try fixtureObject(rowEntity, c)
                        try fixtureSet(row, "GID", gid)
                        try fixtureSet(row, "symbol", "ETH")
                        try fixtureSet(row, "numberOfShares", delta)
                        try fixtureSet(row, "date", precisePlanTimestamp("2026-09-10T09:00:00Z"))
                        try fixtureSet(row, "status", 2)
                        try fixtureSet(row, "account", account)
                        try fixtureSet(row, "investmentHolding", holding)
                        if entity == "InvestmentAccount" && rowEntity == "InvestmentBuyTransaction" {
                            try fixtureSet(row, "amount", -0.1)
                            try fixtureSet(row, "pricePerShare", 10.0)
                        }
                    }
                    if entity == "InvestmentAccount" {
                        let sell = try fixtureObject("InvestmentSellTransaction", c)
                        try fixtureSet(sell, "GID", "w05-sell")
                        try fixtureSet(sell, "symbol", "ETH")
                        try fixtureSet(sell, "numberOfShares", 0.1)
                        try fixtureSet(sell, "amount", 0.1)
                        try fixtureSet(sell, "pricePerShare", 1.0)
                        try fixtureSet(sell, "date", precisePlanTimestamp("2026-09-10T09:30:00Z"))
                        try fixtureSet(sell, "status", 2)
                        try fixtureSet(sell, "account", account)
                        try fixtureSet(sell, "investmentHolding", holding)
                    } else {
                        let other = try fixtureObject("InvestmentHolding", c)
                        try fixtureSet(other, "GID", "w05-peer-holding")
                        try fixtureSet(other, "symbol", "USD")
                        try fixtureSet(other, "investmentObjectType", 1)
                        try fixtureSet(other, "investmentAccount", account)
                        let exchange = try fixtureObject("InvestmentExchangeTransaction", c)
                        try fixtureSet(exchange, "GID", "w05-exchange")
                        try fixtureSet(exchange, "date", precisePlanTimestamp("2026-09-10T09:30:00Z"))
                        try fixtureSet(exchange, "fromInvestmentHolding", holding)
                        try fixtureSet(exchange, "toInvestmentHolding", other)
                        try fixtureSet(exchange, "fromSymbol", "ETH")
                        try fixtureSet(exchange, "toSymbol", "USD")
                        try fixtureSet(exchange, "fromNumberOfShares", -0.1)
                        try fixtureSet(exchange, "toNumberOfShares", 10.0)
                        try fixtureSet(exchange, "account", account)
                    }
                }
                try c.save()
                let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(ofType: NSSQLiteStoreType, at: store, options: nil)
                let result: [String: Any] = ["store_uuid": metadata[NSStoreUUIDKey] as! String,
                    "owner_uri": user.objectID.uriRepresentation().absoluteString]
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            if args.count == 5 && args[4].hasPrefix("--w09-") {
                let account = try fixtureAccount("CashAccount", gid: "w09-account",
                    name: "W09 account", opening: 100, balance: 90, user: user, context: c)
                let source = try fixtureObject("Payee", c)
                try fixtureSet(source, "GID", "w09-source")
                let sourceName = args[4] == "--w09-fuzzy" ? "Merchant East" :
                    (args[4] == "--w09-untrimmed" ? "MERCHANT " :
                    (args[4] == "--w09-control-space" ? "A\u{001C}B" :
                    (args[4] == "--w09-blank-control" ? "\u{001C}" : "MERCHANT")))
                try fixtureSet(source, "name", sourceName)
                try fixtureSet(source, "objectCreationDate", Date())
                try fixtureSet(source, "user", user)
                let survivor = try fixtureObject("Payee", c)
                try fixtureSet(survivor, "GID", "w09-survivor")
                try fixtureSet(survivor, "name", args[4] == "--w09-control-space" ? "A B" : "Merchant")
                try fixtureSet(survivor, "objectCreationDate", Date())
                try fixtureSet(survivor, "user", user)
                let unrelated = try fixtureObject("Payee", c)
                try fixtureSet(unrelated, "GID", "w09-unrelated")
                try fixtureSet(unrelated, "name", "Unrelated")
                try fixtureSet(unrelated, "user", user)
                let transaction = try fixtureWithdrawal("w09-transaction", account: account, context: c)
                try fixtureSet(transaction, "payee", source)
                let history = try fixtureObject("StringHistoryItem", c)
                try fixtureSet(history, "payee", source)
                let scheduled = try fixtureObject("ScheduledWithdrawTransactionHandler", c)
                try fixtureSet(scheduled, "payee", source)
                let paymentPlan = try fixtureObject("PaymentPlan", c)
                try fixtureSet(paymentPlan, "payee", source)
                let card = try fixtureObject("InfoCard", c)
                try fixtureSet(card, "payees", NSSet(objects: source, unrelated))
                try c.save()
                let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
                    ofType: NSSQLiteStoreType, at: store, options: nil)
                let inventory = try payeeInventory(sourceGID: "w09-source",
                                                   survivorGID: "w09-survivor", context: c)
                let encoded = try JSONEncoder().encode(inventory)
                var result = try JSONSerialization.jsonObject(with: encoded) as! [String: Any]
                result["store_uuid"] = metadata[NSStoreUUIDKey] as! String
                FileHandle.standardOutput.write(try JSONSerialization.data(
                    withJSONObject: result, options: [.sortedKeys]))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            if args.count == 5 && args[4].hasPrefix("--w07-") {
                let reverse = args[4] == "--w07-reverse"
                let paired = args[4] == "--w07-paired"
                let sourceCurrency = reverse ? "EUR" : "GBP"
                let destinationCurrency = reverse ? "GBP" : "EUR"
                let sourceAmount = reverse ? -23.0 : -20.0
                let destinationAmount = reverse ? 20.0 : 23.0
                let source = try fixtureAccount(ProcessInfo.processInfo.environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] ?? "CashAccount", gid: "w07-source",
                    name: "W07 source", opening: 100, balance: 80, user: user, context: c)
                let destination = try fixtureAccount(ProcessInfo.processInfo.environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] ?? "CashAccount", gid: "w07-destination",
                    name: "W07 destination", opening: 50, balance: paired ? 73 : 50,
                    user: user, context: c)
                try fixtureSet(source, "currencyName", sourceCurrency)
                try fixtureSet(destination, "currencyName", destinationCurrency)
                func imported(_ entity: String, gid: String, amount: Double,
                              currency: String, date: String,
                              account: NSManagedObject) throws -> NSManagedObject {
                    let row = try fixtureObject(entity, c)
                    try fixtureSet(row, "GID", gid)
                    try fixtureSet(row, "amount", amount)
                    try fixtureSet(row, "originalAmount", amount)
                    try fixtureSet(row, "originalCurrency", currency)
                    try fixtureSet(row, "originalExchangeRate", 1.0)
                    try fixtureSet(row, "currencyExchangeRate", 1.0)
                    try fixtureSet(row, "objectCreationDate", Date())
                    try fixtureSet(row, "date", precisePlanTimestamp(date))
                    try fixtureSet(row, "status", 2)
                    try fixtureSet(row, "flags", 4)
                    try fixtureSet(row, "reconciled", false)
                    try fixtureSet(row, "notes", "Imported fixture")
                    try fixtureSet(row, "desc", "Synthetic conversion")
                    try fixtureSet(row, "voidCheque", 0)
                    try fixtureSet(row, "account", account)
                    return row
                }
                let sourceRow = try imported("WithdrawTransaction", gid: "w07-import-source",
                    amount: sourceAmount, currency: sourceCurrency,
                    date: "2026-09-13T09:30:00+02:00", account: source)
                if args[4] == "--w07-voided" { try fixtureSet(sourceRow, "voidCheque", 1) }
                let tag = try fixtureObject("Tag", c)
                try fixtureSet(tag, "GID", "w07-tag")
                try fixtureSet(tag, "name", "W07")
                try fixtureSet(tag, "objectCreationDate", Date())
                try fixtureSet(tag, "user", user)
                try fixtureSet(sourceRow, "tags", NSSet(object: tag))
                let payee = try fixtureObject("Payee", c)
                try fixtureSet(payee, "GID", "w07-payee")
                try fixtureSet(payee, "name", "W07")
                try fixtureSet(payee, "objectCreationDate", Date())
                try fixtureSet(payee, "user", user)
                try fixtureSet(sourceRow, "payee", payee)
                let category = try fixtureObject("Category", c)
                try fixtureSet(category, "GID", "w07-category")
                try fixtureSet(category, "name", "W07")
                try fixtureSet(category, "objectCreationDate", Date())
                try fixtureSet(category, "type", 1)
                try fixtureSet(category, "user", user)
                let assignment = try fixtureObject("CategoryAssigment", c)
                try fixtureSet(assignment, "amount", sourceAmount)
                try fixtureSet(assignment, "assigmentNumber", 0)
                try fixtureSet(assignment, "category", category)
                try fixtureSet(assignment, "transaction", sourceRow)
                let destinationRow = try paired ? imported("DepositTransaction", gid: "w07-import-destination",
                    amount: destinationAmount, currency: destinationCurrency,
                    date: "2026-09-13T09:31:00+02:00", account: destination) : nil
                if args[4] == "--w07-ambiguous" {
                    _ = try imported("DepositTransaction", gid: "w07-ambiguous",
                        amount: destinationAmount, currency: destinationCurrency,
                        date: "2026-09-13T09:31:00+02:00", account: destination)
                }
                try c.save()
                let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
                    ofType: NSSQLiteStoreType, at: store, options: nil)
                let result: [String: Any] = [
                    "store_uuid": metadata[NSStoreUUIDKey] as! String,
                    "owner_uri": user.objectID.uriRepresentation().absoluteString,
                    "source_numeric_id": durableNumericID(sourceRow.objectID),
                    "destination_numeric_id": destinationRow.map { durableNumericID($0.objectID) } ?? NSNull(),
                    "source_assignment_uri": assignment.objectID.uriRepresentation().absoluteString,
                ]
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            if args.count == 5 && args[4].hasPrefix("--w08-") {
                let units = args[4] == "--w08-units"
                let account = try fixtureAccount(ProcessInfo.processInfo.environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] ?? "InvestmentAccount", gid: "w08-investment",
                    name: "W08 investment", opening: 100, balance: 0, user: user, context: c)
                try fixtureSet(account, "archived", false)
                let payee = try fixtureObject("Payee", c)
                try fixtureSet(payee, "GID", "w08-payee")
                try fixtureSet(payee, "name", "W08")
                try fixtureSet(payee, "user", user)
                let tag = try fixtureObject("Tag", c)
                try fixtureSet(tag, "GID", "w08-tag")
                try fixtureSet(tag, "name", "W08")
                try fixtureSet(tag, "user", user)
                for (gid, type) in [("w08-income", 2), ("w08-expense", 1)] {
                    let category = try fixtureObject("Category", c)
                    try fixtureSet(category, "GID", gid)
                    try fixtureSet(category, "name", gid)
                    try fixtureSet(category, "type", type)
                    try fixtureSet(category, "user", user)
                }
                if units {
                    let holding = try fixtureObject("InvestmentHolding", c)
                    try fixtureSet(holding, "GID", "w08-holding")
                    try fixtureSet(holding, "symbol", "W08")
                    try fixtureSet(holding, "investmentObjectType", 1)
                    try fixtureSet(holding, "openningNumberOfShares", 10.0)
                    try fixtureSet(holding, "pricePerShare", 5.0)
                    try fixtureSet(holding, "investmentAccount", account)
                    let existing = try fixtureObject("InvestmentBuyTransaction", c)
                    try fixtureSet(existing, "GID", "w08-existing-buy")
                    try fixtureSet(existing, "amount", -11.0)
                    try fixtureSet(existing, "originalAmount", -11.0)
                    try fixtureSet(existing, "originalCurrency", "EUR")
                    try fixtureSet(existing, "originalExchangeRate", 0.0)
                    try fixtureSet(existing, "currencyExchangeRate", 0.0)
                    try fixtureSet(existing, "fee", 1.0)
                    try fixtureSet(existing, "originalFee", 0.0)
                    try fixtureSet(existing, "numberOfShares", 2.0)
                    try fixtureSet(existing, "pricePerShare", 5.0)
                    try fixtureSet(existing, "date", precisePlanTimestamp("2026-09-10T09:00:00Z"))
                    try fixtureSet(existing, "objectCreationDate", Date())
                    try fixtureSet(existing, "status", 2)
                    try fixtureSet(existing, "flags", 0)
                    try fixtureSet(existing, "reconciled", true)
                    try fixtureSet(existing, "symbol", "W08")
                    try fixtureSet(existing, "account", account)
                    try fixtureSet(existing, "investmentHolding", holding)
                }
                try c.save()
                let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
                    ofType: NSSQLiteStoreType, at: store, options: nil)
                let result: [String: Any] = [
                    "store_uuid": metadata[NSStoreUUIDKey] as! String,
                    "owner_uri": user.objectID.uriRepresentation().absoluteString,
                ]
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            if args.count == 5 && ["--w06", "--w06-backdated", "--w06-unmarked", "--w06-linked"].contains(args[4]) {
                let account = try fixtureObject("InvestmentAccount", c)
                try fixtureSet(account, "GID", "w06-investment")
                try fixtureSet(account, "name", "W06 investment")
                try fixtureSet(account, "objectCreationDate", Date())
                try fixtureSet(account, "openingBalance", 100.0)
                try fixtureSet(account, "ballance", 0.0)
                try fixtureSet(account, "currencyName", ProcessInfo.processInfo.environment["MONEYWIZ_TEST_CURRENCY"] ?? "GBP")
                try fixtureSet(account, "archived", false)
                try fixtureSet(account, "user", user)
                func adjustment(_ gid: String, amount: Double, total: Double, date: String) throws -> NSManagedObject {
                    let row = try fixtureObject("ReconcileTransaction", c)
                    try fixtureSet(row, "GID", gid)
                    try fixtureSet(row, "amount", amount)
                    try fixtureSet(row, "reconcileAmount", total)
                    try fixtureSet(row, "date", precisePlanTimestamp(date))
                    try fixtureSet(row, "objectCreationDate", Date())
                    try fixtureSet(row, "desc", "New balance")
                    try fixtureSet(row, "notes", "")
                    try fixtureSet(row, "status", 2)
                    try fixtureSet(row, "flags", 0)
                    try fixtureSet(row, "voidCheque", 0)
                    try fixtureSet(row, "reconciled", false)
                    try fixtureSet(row, "account", account)
                    if row.entity.propertiesByName["user"] != nil {
                        try fixtureSet(row, "user", user)
                    }
                    return row
                }
                _ = try adjustment("w06-older", amount: 10, total: 110,
                                   date: "2026-09-10T12:00:00Z")
                let targetDate = "2026-09-11T12:00:00.408332Z"
                let target = try adjustment("w06-target", amount: -2, total: 108, date: targetDate)
                if args[4] == "--w06-backdated" {
                    let row = try fixtureObject("DepositTransaction", c)
                    try fixtureSet(row, "GID", "w06-backdated-cash")
                    try fixtureSet(row, "amount", 0.01)
                    try fixtureSet(row, "originalAmount", 0.01)
                    try fixtureSet(row, "originalCurrency", "GBP")
                    try fixtureSet(row, "originalExchangeRate", 1.0)
                    try fixtureSet(row, "currencyExchangeRate", 1.0)
                    try fixtureSet(row, "date", precisePlanTimestamp("2026-09-09T12:00:00Z"))
                    try fixtureSet(row, "objectCreationDate", Date())
                    try fixtureSet(row, "status", 2)
                    try fixtureSet(row, "account", account)
                }
                if args[4] == "--w06-linked" {
                    let payee = try fixtureObject("Payee", c)
                    try fixtureSet(payee, "GID", "w06-dependent-payee")
                    try fixtureSet(payee, "name", "Dependent")
                    try fixtureSet(payee, "user", user)
                    try fixtureSet(target, "payee", payee)
                }
                try c.save()
                let finalMetadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
                    ofType: NSSQLiteStoreType, at: store, options: nil)
                let result: [String: Any] = [
                    "store_uuid": finalMetadata[NSStoreUUIDKey] as! String,
                    "owner_uri": user.objectID.uriRepresentation().absoluteString,
                    "target_numeric_id": durableNumericID(target.objectID),
                    "target_date": targetDate,
                ]
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]))
                FileHandle.standardOutput.write(Data([10]))
                return
            }
            let accountEntity = ProcessInfo.processInfo.environment["MONEYWIZ_TEST_ACCOUNT_ENTITY"] ?? "CashAccount"
            guard supportedAccountEntities.contains(accountEntity) else { throw HostError.message("invalid fixture account type") }
            let account = try fixtureObject(accountEntity, c)
            try fixtureSet(account,"GID","w01-account"); try fixtureSet(account,"name","W01"); try fixtureSet(account,"objectCreationDate",Date()); try fixtureSet(account,"openingBalance",10.0); try fixtureSet(account,"ballance",0.0); try fixtureSet(account,"currencyName","EUR"); try fixtureSet(account,"user",user)
            let payee = try fixtureObject("Payee", c); try fixtureSet(payee,"GID","w01-payee"); try fixtureSet(payee,"name","W01"); try fixtureSet(payee,"objectCreationDate",Date()); try fixtureSet(payee,"user",user)
            let secondPayee = try fixtureObject("Payee", c); try fixtureSet(secondPayee,"GID","w03-payee"); try fixtureSet(secondPayee,"name","W03"); try fixtureSet(secondPayee,"objectCreationDate",Date()); try fixtureSet(secondPayee,"user",user)
            let category = try fixtureObject("Category", c); try fixtureSet(category,"GID","w01-category"); try fixtureSet(category,"name","W01"); try fixtureSet(category,"objectCreationDate",Date()); try fixtureSet(category,"type",1); try fixtureSet(category,"user",user)
            let secondCategory = try fixtureObject("Category", c); try fixtureSet(secondCategory,"GID","w03-category"); try fixtureSet(secondCategory,"name","W03"); try fixtureSet(secondCategory,"objectCreationDate",Date()); try fixtureSet(secondCategory,"type",1); try fixtureSet(secondCategory,"user",user)
            let income = try fixtureObject("Category", c); try fixtureSet(income,"GID","w01-income-category"); try fixtureSet(income,"name","Income"); try fixtureSet(income,"objectCreationDate",Date()); try fixtureSet(income,"type",2); try fixtureSet(income,"user",user)
            let tag = try fixtureObject("Tag", c); try fixtureSet(tag,"GID","w01-tag"); try fixtureSet(tag,"name","W01"); try fixtureSet(tag,"objectCreationDate",Date()); try fixtureSet(tag,"user",user)
            let foreignPayee = try fixtureObject("Payee", c); try fixtureSet(foreignPayee,"GID","w01-foreign-payee"); try fixtureSet(foreignPayee,"name","Foreign"); try fixtureSet(foreignPayee,"objectCreationDate",Date()); try fixtureSet(foreignPayee,"user",foreignUser)
            let foreignCategory = try fixtureObject("Category", c); try fixtureSet(foreignCategory,"GID","w01-foreign-category"); try fixtureSet(foreignCategory,"name","Foreign"); try fixtureSet(foreignCategory,"objectCreationDate",Date()); try fixtureSet(foreignCategory,"type",2); try fixtureSet(foreignCategory,"user",foreignUser)
            let foreignTag = try fixtureObject("Tag", c); try fixtureSet(foreignTag,"GID","w01-foreign-tag"); try fixtureSet(foreignTag,"name","Foreign"); try fixtureSet(foreignTag,"objectCreationDate",Date()); try fixtureSet(foreignTag,"user",foreignUser)
            _ = try fixtureWithdrawal("w01-original", account: account, context: c)
            _ = try fixtureTransaction("DepositTransaction", gid: "w02-deposit", amount: 10,
                                       account: account, payee: payee, tag: tag, context: c)
            _ = try fixtureTransaction("WithdrawTransaction", gid: "w02-withdraw", amount: -10,
                                       account: account, payee: payee, tag: tag, context: c)
            let refundOriginal = try fixtureTransaction("WithdrawTransaction", gid: "w02-refund-original", amount: -10,
                                                        account: account, payee: payee, tag: tag, context: c)
            let refund = try fixtureTransaction("RefundTransaction", gid: "w02-refund", amount: 2,
                                                account: account, payee: payee, tag: tag, context: c)
            try fixtureRefundLink(refundOriginal, refund: refund, context: c)
            let secondRefund = try fixtureTransaction("RefundTransaction", gid: "w02-refund-second", amount: 3,
                                                      account: account, payee: payee, tag: tag, context: c)
            try fixtureRefundLink(refundOriginal, refund: secondRefund, context: c)
            let categorized = try fixtureTransaction("WithdrawTransaction", gid: "w02-categorized", amount: -4,
                                                     account: account, payee: payee, tag: tag, context: c)
            try fixtureCategoryAssignment(categorized, category: category, amount: -4, context: c)
            let reconciled = try fixtureTransaction("WithdrawTransaction", gid: "w02-reconciled", amount: -3,
                                                    account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(reconciled, "reconciled", true)
            let flagged = try fixtureTransaction("WithdrawTransaction", gid: "w02-flagged", amount: -3,
                                                 account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(flagged, "flags", 1)
            let inactive = try fixtureTransaction("WithdrawTransaction", gid: "w02-inactive", amount: -3,
                                                  account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(inactive, "status", 0)
            let voided = try fixtureTransaction("WithdrawTransaction", gid: "w02-void", amount: -3,
                                                account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(voided, "voidCheque", 1)
            let scheduled = try fixtureTransaction("WithdrawTransaction", gid: "w02-scheduled", amount: -3,
                                                   account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(scheduled, "autoSkipLinkedScheduledTransactionGID", "w02-schedule")
            let fee = try fixtureTransaction("WithdrawTransaction", gid: "w02-fee", amount: -3,
                                             account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(fee, "fee", 1.0)
            let investment = try fixtureTransaction("WithdrawTransaction", gid: "w02-investment", amount: -3,
                                                    account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(investment, "investmentSymbol", "W02")
            let fx = try fixtureTransaction("WithdrawTransaction", gid: "w02-fx", amount: -3,
                                            account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(fx, "currencyExchangeRate", 1.1)
            try fixtureSet(fx, "originalExchangeRate", 1.1)
            let nativeEmptySchedule = try fixtureTransaction("WithdrawTransaction", gid: "w02-empty-schedule", amount: -3,
                                                            account: account, payee: payee, tag: tag, context: c)
            try fixtureSet(nativeEmptySchedule, "autoSkipLinkedScheduledTransactionGID", "")
            let otherAccount = try fixtureAccount("CashAccount", gid: "w01-other-account", name: "Other", opening: 10, balance: 0, user: user, context: c)
            _ = try fixtureWithdrawal("w01-other-original", account: otherAccount, context: c)
            _ = try fixtureAccount("BankChequeAccount", gid: "w01-bank-account", name: "Bank", opening: 0, balance: 0, user: user, context: c)
            _ = try fixtureAccount("InvestmentAccount", gid: "w01-investment-account", name: "Investment", opening: 0, balance: 0, user: user, context: c)
            try c.save()
            let finalMetadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(ofType: NSSQLiteStoreType, at: store, options: nil)
            let allTransactions = try c.fetch(NSFetchRequest<NSManagedObject>(entityName: "Transaction"))
                .filter { ($0.value(forKey: "account") as? NSManagedObject)?.objectID == account.objectID }
            let accountGIDs = allTransactions.compactMap { $0.value(forKey: "GID") as? String }.sorted()
            guard accountGIDs.count == allTransactions.count else { throw HostError.message("fixture transaction lacks GID") }
            let result: [String: Any] = [
                "store_uuid": finalMetadata[NSStoreUUIDKey] as! String,
                "owner_uri": user.objectID.uriRepresentation().absoluteString,
                "transaction_gids": accountGIDs,
            ]
            let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]); FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
        } catch { FileHandle.standardError.write(Data("error: \(error.localizedDescription)\n".utf8)); exit(2) }
    }
}
