import { describe, it, expect } from "vitest";
import { mintToken, verifyToken, authenticate, login } from "../src/auth.js";

const env = { POSITIONS_SESSION_SECRET: "test-secret-abc123-abc123-abc123", POSITIONS_AUTH_PASSPHRASE: "hunter2-passphrase" };

function bearer(token) {
  return new Request("https://x/positions", { headers: { authorization: `Bearer ${token}` } });
}

describe("token mint/verify", () => {
  it("round-trips a valid token", async () => {
    const t = await mintToken(env, "owner");
    const p = await verifyToken(env, t);
    expect(p).not.toBeNull();
    expect(p.uid).toBe("owner");
  });

  it("rejects a tampered payload", async () => {
    const t = await mintToken(env, "owner");
    const [, sig] = t.split(".");
    const forged = `${btoa('{"uid":"attacker","exp":9999999999}').replace(/=+$/, "")}.${sig}`;
    expect(await verifyToken(env, forged)).toBeNull();
  });

  it("rejects an expired token", async () => {
    const past = Date.now() - 40 * 24 * 60 * 60 * 1000; // 40 days ago; TTL is 30
    const t = await mintToken(env, "owner", past);
    expect(await verifyToken(env, t)).toBeNull();
  });

  it("rejects garbage and empty", async () => {
    expect(await verifyToken(env, "")).toBeNull();
    expect(await verifyToken(env, "no-dot")).toBeNull();
    expect(await verifyToken(env, "a.b")).toBeNull();
  });

  it("rejects a token signed with a different secret", async () => {
    const t = await mintToken({ ...env, POSITIONS_SESSION_SECRET: "other-secret" }, "owner");
    expect(await verifyToken(env, t)).toBeNull();
  });
});

describe("authenticate()", () => {
  it("returns user_id for a valid bearer", async () => {
    const t = await mintToken(env, "owner");
    expect(await authenticate(bearer(t), env)).toEqual({ user_id: "owner" });
  });
  it("returns null with no/other header", async () => {
    expect(await authenticate(new Request("https://x/"), env)).toBeNull();
    expect(await authenticate(new Request("https://x/", { headers: { authorization: "Basic xyz" } }), env)).toBeNull();
  });
});

describe("login()", () => {
  it("mints a usable token on correct passphrase", async () => {
    const t = await login(env, "hunter2-passphrase");
    expect(t).toBeTruthy();
    expect(await verifyToken(env, t)).not.toBeNull();
  });
  it("returns null on wrong passphrase", async () => {
    expect(await login(env, "wrong")).toBeNull();
    expect(await login(env, "")).toBeNull();
    expect(await login(env, null)).toBeNull();
  });
  it("throws if passphrase secret is unconfigured", async () => {
    await expect(login({ POSITIONS_SESSION_SECRET: "s" }, "x")).rejects.toThrow();
  });
});
