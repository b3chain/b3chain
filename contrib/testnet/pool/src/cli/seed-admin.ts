// Operator: create the first user account, mark it verified and admin.
//
// USAGE:
//   tsx src/cli/seed-admin.ts admin@b3chain.org 'a-strong-password'

import * as argon2 from "argon2";
import { query, closePool } from "../lib/db";

async function main(): Promise<void> {
    const [email, password] = process.argv.slice(2);
    if (!email || !password) {
        console.error("usage: seed-admin <email> <password>");
        process.exit(2);
    }
    const hash = await argon2.hash(password, { type: argon2.argon2id });
    const exists = await query("SELECT id FROM users WHERE email = $1", [email]);
    if (exists.length > 0) {
        await query(
            "UPDATE users SET password_hash = $1, email_verified = TRUE, is_admin = TRUE WHERE email = $2",
            [hash, email]
        );
        console.log("updated existing user; promoted to admin & verified");
    } else {
        await query(
            "INSERT INTO users(email, password_hash, email_verified, is_admin) VALUES ($1, $2, TRUE, TRUE)",
            [email, hash]
        );
        console.log("created admin user");
    }
    await closePool();
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
