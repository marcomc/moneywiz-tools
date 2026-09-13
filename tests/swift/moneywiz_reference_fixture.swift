import CoreData
import Foundation

let fixtureMoneyWizBundleIdentifiers = [
    "com.moneywiz.personalfinance-setapp",
    "com.moneywiz.personalfinance",
]
let fixtureProfileID = "moneywiz-2026-model-48"
let fixtureModelChecksum = "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ="

struct FixtureArguments {
    let store: URL
    let model: URL
    let app: URL
    let plan: URL
}

enum FixtureError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self { case let .message(message): return message }
    }
}

func parseFixtureArguments() throws -> FixtureArguments {
    let values = Array(CommandLine.arguments.dropFirst())
    guard values.count == 8 else {
        throw FixtureError.message("usage: fixture --store PATH --model PATH --app PATH --plan PATH")
    }
    var parsed: [String: String] = [:]
    var index = 0
    while index < values.count {
        let flag = values[index]
        guard ["--store", "--model", "--app", "--plan"].contains(flag), parsed[flag] == nil else {
            throw FixtureError.message("invalid fixture arguments")
        }
        parsed[flag] = values[index + 1]
        index += 2
    }
    guard let store = parsed["--store"], let model = parsed["--model"],
          let app = parsed["--app"], let plan = parsed["--plan"] else {
        throw FixtureError.message("fixture arguments are incomplete")
    }
    return FixtureArguments(
        store: URL(fileURLWithPath: store), model: URL(fileURLWithPath: model),
        app: URL(fileURLWithPath: app), plan: URL(fileURLWithPath: plan)
    )
}

func insert(_ name: String, into context: NSManagedObjectContext) throws -> NSManagedObject {
    guard let entity = NSEntityDescription.entity(forEntityName: name, in: context) else {
        throw FixtureError.message("installed model does not contain required entity \(name)")
    }
    return NSManagedObject(entity: entity, insertInto: context)
}

func set(_ object: NSManagedObject, _ key: String, _ value: Any?) throws {
    guard object.entity.propertiesByName[key] != nil else {
        throw FixtureError.message("\(object.entity.name ?? "object") lacks required property \(key)")
    }
    object.setValue(value, forKey: key)
}

func makeFixture(_ arguments: FixtureArguments) throws -> [String: String] {
    let manager = FileManager.default
    guard !manager.fileExists(atPath: arguments.store.path) else {
        throw FixtureError.message("fixture store must not already exist")
    }
    guard let model = NSManagedObjectModel(contentsOf: arguments.model) else {
        throw FixtureError.message("cannot load supplied compiled model")
    }
    guard let appBundle = Bundle(url: arguments.app),
          let bundleID = appBundle.bundleIdentifier,
          let version = appBundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String else {
        throw FixtureError.message("cannot read supplied MoneyWiz app metadata")
    }
    guard fixtureMoneyWizBundleIdentifiers.contains(bundleID) else {
        throw FixtureError.message("supplied app is not a supported MoneyWiz bundle")
    }
    try manager.createDirectory(
        at: arguments.store.deletingLastPathComponent(), withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
    )
    configureTransformers()
    let container = NSPersistentContainer(name: "MoneyWizReferenceFixture", managedObjectModel: model)
    let description = NSPersistentStoreDescription(url: arguments.store)
    description.type = NSSQLiteStoreType
    description.shouldAddStoreAsynchronously = false
    container.persistentStoreDescriptions = [description]
    var loadError: Error?
    container.loadPersistentStores { _, error in loadError = error }
    if let loadError { throw loadError }

    let context = container.viewContext
    let user = try insert("User", into: context)
    let account = try insert("CashAccount", into: context)
    try set(account, "GID", "synthetic-account")
    try set(account, "currencyName", "EUR")
    try set(account, "ballance", 12.5)
    try set(account, "name", "Synthetic cash")
    try set(account, "user", user)
    let payee = try insert("Payee", into: context)
    try set(payee, "GID", "synthetic-payee")
    try set(payee, "name", "Synthetic")
    try set(payee, "user", user)
    let transaction = try insert("WithdrawTransaction", into: context)
    try set(transaction, "GID", "synthetic-tx")
    try set(transaction, "account", account)
    try context.save()

    let metadata = try NSPersistentStoreCoordinator.metadataForPersistentStore(
        ofType: NSSQLiteStoreType, at: arguments.store, options: nil
    )
    guard let storeUUID = metadata[NSStoreUUIDKey] as? String else {
        throw FixtureError.message("synthetic store has no UUID")
    }
    let ownerURI = user.objectID.uriRepresentation().absoluteString
    let modelPath = arguments.model.standardizedFileURL.path
    var plan: [String: Any] = [
        "contract_version": 2,
        "operation_schema_version": 1,
        "plan_id": "synthetic-reference-plan",
        "profile_id": fixtureProfileID,
        "model_checksum": fixtureModelChecksum,
        "store_identity": ["store_uuid": storeUUID],
        "owner_uri": ownerURI,
        "app_identity": [
            "bundle_id": bundleID, "version": version, "path": arguments.app.standardizedFileURL.path,
            "model_path": modelPath,
        ],
        "capability": "write.reassign-payees-by-id",
        "created_at": "2026-09-13T00:00:00Z",
        "timezone": "Europe/Rome",
        "source_interval": ["start": "2026-09-13T00:00:00Z", "end": "2026-09-13T00:00:00Z"],
        "source_evidence_refs": ["synthetic://moneywiz-reference-fixture"],
        "expected_account_gid": "synthetic-account",
        "expected_cached_account_balance": "12.5",
        "currency_unit": "EUR",
        "source_event_id": "synthetic-reference-event",
        "operations": [[
            "operation_id": "synthetic-reassign-payee",
            "kind": "reassign_payee",
            "capability": "write.reassign-payees-by-id",
            "transaction_entity": "WithdrawTransaction",
            "transaction_gid": "synthetic-tx",
            "expected_old_payee_gid": NSNull(),
            "target_payee_gid": "synthetic-payee",
            "owner_uri": ownerURI,
            "source_event_id": "synthetic-reference-event",
            "expected_postcondition": ["payee_gid": "synthetic-payee"],
            "allowed_changed_fields": ["payee"],
        ]],
    ]
    plan["plan_digest"] = try canonicalV2Digest(plan)
    let planData = try JSONSerialization.data(withJSONObject: plan, options: [.sortedKeys, .withoutEscapingSlashes])
    try manager.createDirectory(
        at: arguments.plan.deletingLastPathComponent(), withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
    )
    try planData.write(to: arguments.plan, options: .atomic)
    try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: arguments.plan.path)
    try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: arguments.store.path)
    return ["store": arguments.store.path, "plan": arguments.plan.path]
}

@main
struct MoneyWizReferenceFixture {
    static func main() {
        do {
            let paths = try makeFixture(try parseFixtureArguments())
            let data = try JSONSerialization.data(withJSONObject: paths, options: [.sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([0x0A]))
        } catch {
            FileHandle.standardError.write(Data("error: \(error.localizedDescription)\n".utf8))
            exit(2)
        }
    }
}
