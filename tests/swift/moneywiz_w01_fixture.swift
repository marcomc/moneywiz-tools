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
            if args.first?.hasPrefix("--crash-") == true {
                try runFixtureCrash(args)
            }
            guard (args.count == 4 || args.count == 5), args[0] == "--store", args[2] == "--model",
                  args.count == 4 || args[4] == "--unmarked" else { throw HostError.message("usage") }
            let store = URL(fileURLWithPath: args[1]), modelURL = URL(fileURLWithPath: args[3])
            guard !FileManager.default.fileExists(atPath: store.path), let model = NSManagedObjectModel(contentsOf: modelURL) else { throw HostError.message("invalid disposable fixture inputs") }
            configureTransformers()
            let container = NSPersistentContainer(name: "W01", managedObjectModel: model)
            let description = NSPersistentStoreDescription(url: store); description.shouldAddStoreAsynchronously = false
            container.persistentStoreDescriptions = [description]
            var error: Error?; container.loadPersistentStores { _, value in error = value }; if let error { throw error }
            guard let persistentStore = container.persistentStoreCoordinator.persistentStores.first else { throw HostError.message("fixture has no persistent store") }
            if args.count == 4 {
                var storeMetadata = persistentStore.metadata ?? [:]
                storeMetadata["MoneyWizToolsDisposableFixture"] = "W01-v1"
                container.persistentStoreCoordinator.setMetadata(storeMetadata, for: persistentStore)
            }
            let c = container.viewContext
            let user = try fixtureObject("User", c)
            try fixtureSet(user, "syncLogin", "w01-fixture@example.invalid")
            let foreignUser = try fixtureObject("User", c)
            try fixtureSet(foreignUser, "syncLogin", "w01-foreign@example.invalid")
            let account = try fixtureObject("CashAccount", c)
            try fixtureSet(account,"GID","w01-account"); try fixtureSet(account,"name","W01"); try fixtureSet(account,"objectCreationDate",Date()); try fixtureSet(account,"openingBalance",10.0); try fixtureSet(account,"ballance",0.0); try fixtureSet(account,"currencyName","EUR"); try fixtureSet(account,"user",user)
            let payee = try fixtureObject("Payee", c); try fixtureSet(payee,"GID","w01-payee"); try fixtureSet(payee,"name","W01"); try fixtureSet(payee,"objectCreationDate",Date()); try fixtureSet(payee,"user",user)
            let category = try fixtureObject("Category", c); try fixtureSet(category,"GID","w01-category"); try fixtureSet(category,"name","W01"); try fixtureSet(category,"objectCreationDate",Date()); try fixtureSet(category,"type",1); try fixtureSet(category,"user",user)
            let income = try fixtureObject("Category", c); try fixtureSet(income,"GID","w01-income-category"); try fixtureSet(income,"name","Income"); try fixtureSet(income,"objectCreationDate",Date()); try fixtureSet(income,"type",2); try fixtureSet(income,"user",user)
            let tag = try fixtureObject("Tag", c); try fixtureSet(tag,"GID","w01-tag"); try fixtureSet(tag,"name","W01"); try fixtureSet(tag,"objectCreationDate",Date()); try fixtureSet(tag,"user",user)
            let foreignPayee = try fixtureObject("Payee", c); try fixtureSet(foreignPayee,"GID","w01-foreign-payee"); try fixtureSet(foreignPayee,"name","Foreign"); try fixtureSet(foreignPayee,"objectCreationDate",Date()); try fixtureSet(foreignPayee,"user",foreignUser)
            let foreignCategory = try fixtureObject("Category", c); try fixtureSet(foreignCategory,"GID","w01-foreign-category"); try fixtureSet(foreignCategory,"name","Foreign"); try fixtureSet(foreignCategory,"objectCreationDate",Date()); try fixtureSet(foreignCategory,"type",2); try fixtureSet(foreignCategory,"user",foreignUser)
            let foreignTag = try fixtureObject("Tag", c); try fixtureSet(foreignTag,"GID","w01-foreign-tag"); try fixtureSet(foreignTag,"name","Foreign"); try fixtureSet(foreignTag,"objectCreationDate",Date()); try fixtureSet(foreignTag,"user",foreignUser)
            _ = try fixtureWithdrawal("w01-original", account: account, context: c)
            let otherAccount = try fixtureAccount("CashAccount", gid: "w01-other-account", name: "Other", opening: 10, balance: 0, user: user, context: c)
            _ = try fixtureWithdrawal("w01-other-original", account: otherAccount, context: c)
            _ = try fixtureAccount("BankChequeAccount", gid: "w01-bank-account", name: "Bank", opening: 0, balance: 0, user: user, context: c)
            _ = try fixtureAccount("InvestmentAccount", gid: "w01-investment-account", name: "Investment", opening: 0, balance: 0, user: user, context: c)
            try c.save()
            let finalMetadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(ofType: NSSQLiteStoreType, at: store, options: nil)
            let result: [String:String] = ["store_uuid": finalMetadata[NSStoreUUIDKey] as! String, "owner_uri": user.objectID.uriRepresentation().absoluteString]
            let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]); FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
        } catch { FileHandle.standardError.write(Data("error: \(error.localizedDescription)\n".utf8)); exit(2) }
    }
}
