const PREFIXES = ["/dashboard", "/blocks", "/getting-started", "/admin"];

/** Return a same-site path we are willing to send the browser to after login. */
export function safeNext(next: string): string {
    if (typeof next !== "string") return "/dashboard";
    if (next === "/") return "/";
    if (!next.startsWith("/") || next.startsWith("//") || next.includes("\\") || next.includes("\0")) {
        return "/dashboard";
    }
    const path = next.split("?")[0]!.split("#")[0]!;
    for (const prefix of PREFIXES) {
        if (path === prefix || path.startsWith(prefix + "/")) return next;
    }
    return "/dashboard";
}
