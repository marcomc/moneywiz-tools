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
    let account = transaction.value(forKey: "account") as? NSManagedObject
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
    let plan = try JSONDecoder().decode(WriterPlanV2.self, from: data)
    try validateWriterPlanV2(plan, rawPlan: raw)
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
    let plan = try JSONDecoder().decode(WriterPlanV2.self, from: data)
    try validateWriterPlanV2(plan, rawPlan: raw)
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
            if args.first?.hasPrefix("--crash-") == true {
                try runFixtureCrash(args)
            }
            guard (args.count == 4 || args.count == 5), args[0] == "--store", args[2] == "--model",
                  args.count == 4 || ["--unmarked", "--w06", "--w06-unmarked", "--w06-linked"].contains(args[4]) else {
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
            if args.count == 4 || ["--w06", "--w06-linked"].contains(args[4]) {
                var storeMetadata = persistentStore.metadata ?? [:]
                storeMetadata["MoneyWizToolsDisposableFixture"] = "W01-v1"
                container.persistentStoreCoordinator.setMetadata(storeMetadata, for: persistentStore)
            }
            let c = container.viewContext
            let user = try fixtureObject("User", c)
            try fixtureSet(user, "syncLogin", "w01-fixture@example.invalid")
            let foreignUser = try fixtureObject("User", c)
            try fixtureSet(foreignUser, "syncLogin", "w01-foreign@example.invalid")
            if args.count == 5 && ["--w06", "--w06-unmarked", "--w06-linked"].contains(args[4]) {
                let account = try fixtureObject("InvestmentAccount", c)
                try fixtureSet(account, "GID", "w06-investment")
                try fixtureSet(account, "name", "W06 investment")
                try fixtureSet(account, "objectCreationDate", Date())
                try fixtureSet(account, "openingBalance", 100.0)
                try fixtureSet(account, "ballance", 0.0)
                try fixtureSet(account, "currencyName", "GBP")
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
            let account = try fixtureObject("CashAccount", c)
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
            try fixtureSet(inactive, "status", 2)
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
