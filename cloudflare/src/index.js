// A tiny Worker that wakes the WalletLedger container and passes every request through to it.
//
//   Telegram  --->  this Worker  --->  container (the same Docker image you can run anywhere)
//   Browser   --->  this Worker  --->  /d/<token>  (dashboard)
//
// The container sleeps when nobody is using it and starts again on the next request (a few seconds).
// Its disk is erased every time it sleeps, so data must live in Postgres (DB_MODE=postgres).
import { Container } from "@cloudflare/containers";

// Secrets set with `npx wrangler secret put NAME`. Only the ones you set are passed on.
const PASS_THROUGH = [
  "TELEGRAM_BOT_TOKEN",
  "SECRET_KEY",
  "DATABASE_URL", // postgresql://user:password@host:5432/dbname?sslmode=require
  "TELEGRAM_WEBHOOK_SECRET",
  "ALLOWED_CHAT_IDS",
  "ADMIN_CHAT_IDS",
  "GEMINI_API_KEYS",
  "OPENAI_API_KEYS",
  "ANTHROPIC_API_KEYS",
  "GROQ_API_KEYS",
  "OPENROUTER_API_KEYS",
  "XAI_API_KEYS",
  "DEEPSEEK_API_KEYS",
  "MISTRAL_API_KEYS",
];

export class WalletLedger extends Container {
  defaultPort = 8080; // the Dockerfile listens on $PORT, default 8080
  sleepAfter = "20m"; // stop after 20 idle minutes; the next request wakes it

  constructor(ctx, env) {
    super(ctx, env);
    const publicUrl = (env.PUBLIC_URL || "").replace(/\/$/, "");
    const vars = {
      DB_MODE: "postgres",
      USE_WEBHOOK: "true", // Telegram pushes messages to us; polling cannot work while asleep
      PUBLIC_URL: publicUrl,
      WEBHOOK_URL: `${publicUrl}/bot/webhook`,
    };
    for (const name of PASS_THROUGH) {
      if (env[name]) vars[name] = env[name];
    }
    this.envVars = vars;
  }
}

export default {
  async fetch(request, env) {
    // One instance is plenty for a personal or small-team bot (SQL data lives in Postgres anyway).
    return env.WALLETLEDGER.getByName("main").fetch(request);
  },
};
