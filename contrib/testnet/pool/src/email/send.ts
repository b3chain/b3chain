import nodemailer, { Transporter } from "nodemailer";
import type SMTPTransport from "nodemailer/lib/smtp-transport";
import { config } from "../config";
import { Logger } from "../lib/logger";

let transporter: Transporter | null = null;

function getTransporter(): Transporter {
    if (!transporter) {
        const opts: SMTPTransport.Options = {
            host: config.smtp.host,
            port: config.smtp.port,
            secure: false,
            requireTLS: false,
            tls: { rejectUnauthorized: false },
        };
        if (config.smtp.user) {
            opts.auth = {
                user: config.smtp.user,
                pass: config.smtp.pass,
            };
        }
        transporter = nodemailer.createTransport(opts);
    }
    return transporter;
}

export async function sendEmail(
    to: string,
    subject: string,
    body: string,
    log?: Logger
): Promise<void> {
    try {
        await getTransporter().sendMail({
            from: config.smtp.from,
            to,
            subject,
            text: body,
        });
        log?.info({ to, subject }, "email sent");
    } catch (e) {
        log?.error({ to, subject, err: (e as Error).message }, "email failed");
        throw e;
    }
}
