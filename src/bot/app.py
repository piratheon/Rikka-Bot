import asyncio
import json
import os
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

try:
    from src.config import Config
except ModuleNotFoundError:
    # Allow running this file directly (e.g. `python src/bot/app.py`) by
    # adding the repository root to sys.path so `src` is importable.
    import sys
    import os

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from src.config import Config


def _extract_response_text(resp: dict) -> str:
    # Try standardized "output" first
    if not resp:
        return ""
    if "output" in resp:
        return resp["output"] or ""
    # Fallback to OpenAI / OpenRouter style in case raw_response is used or provider isn't standardized
    try:
        choices = resp.get("choices")
        if choices and isinstance(choices, list):
            first = choices[0]
            # Chat message shape
            msg = first.get("message") if isinstance(first, dict) else None
            if msg and isinstance(msg, dict):
                return msg.get("content") or ""
            # Completion text shape
            text = first.get("text")
            if text:
                return text
    except Exception:
        pass
    # Some providers return top-level "output_text" or "output"
    for k in ("output_text", "text"):
        if isinstance(resp.get(k), str):
            return resp.get(k)
    # As a last resort, stringify the response
    try:
        return str(resp)
    except Exception:
        return ""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "<b>Rikka</b> is awake, Oni-San~\nSend /help for commands."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Wake Rikka and show onboarding\n"
        "/help - Show this help message\n"
        "/delete_me - Delete all your stored data (confirmation required)\n\n"
        "To submit API keys, send a message containing provider:key pairs, for example:\n"
        "openrouter:\"sk-...\"  groq:\"gsk_...\"  google:AIza...\n"
        "Keys will be validated and stored encrypted."
    )


async def addkey_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add API key(s) via command. Usage: /addkey provider:key or /addkey openrouter:"sk-..."""
    from src.utils.parse_keys import parse_keys
    from src.db.key_store import init_db, upsert_user, add_api_key

    raw = " ".join(context.args) if context.args else (update.message.text or "")
    # remove the leading command if present
    if raw.startswith("/addkey"):
        parts = raw.split(None, 1)
        raw = parts[1] if len(parts) > 1 else ""

    # First try regex parser (provider:key or provider:"key")
    keys = parse_keys(raw)
    # Fallback: allow `provider key` pairs or simple `provider key, provider2 key2`
    allowed_providers = ["gemini", "google", "openrouter", "groq", "anthropic", "openai"]
    
    if not keys:
        tokens = [t.strip() for t in raw.replace(',',' ').split() if t.strip()]
        # accept pairs of (provider, key)
        if len(tokens) >= 2:
            i = 0
            while i + 1 < len(tokens):
                prov = tokens[i].lower()
                val = tokens[i+1]
                if prov in allowed_providers:
                    # strip surrounding quotes if any
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    keys[prov] = val
                i += 2

    if not keys:
        await update.message.reply_text('Usage: /addkey provider:"<key>" — e.g. /addkey openrouter:"sk-..."')
        return

    await init_db()
    tg_user = update.effective_user
    user_id = await upsert_user(tg_user.id, tg_user.username)

    from src.providers.provider_pool import ProviderPool
    pool = ProviderPool()

    results = []
    for provider, raw in keys.items():
        try:
            kid = await add_api_key(user_id, provider, raw)
            # Validate the key once upon receipt
            try:
                ok = await pool.get_healthy_key(user_id, provider)
                status = "valid" if ok else "invalid"
                results.append(f"{provider}: stored (id={kid}), status: {status}")
            except Exception as e:
                results.append(f"{provider}: stored (id={kid}), validation error: {e}")
        except Exception as e:
            results.append(f"{provider}: error storing key: {e}")

    await update.message.reply_text("\n".join(results))


async def delete_me_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Yes, delete everything", callback_data="confirm_delete"),
            InlineKeyboardButton("Cancel", callback_data="cancel_delete"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Are you sure you want to delete all your data? This cannot be undone.",
        reply_markup=reply_markup,
    )


async def key_submission_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    from src.utils.logger import logger
    logger.info("incoming_message", user_id=update.effective_user.id, text=(text[:200] if text else ""))
    
    # Quick heuristic: if contains provider:key pairs, parse and store
    from src.utils.parse_keys import parse_keys
    from src.db.key_store import upsert_user, add_api_key, init_db, list_api_keys
    from src.db.chat_store import add_chat_message, get_chat_history, get_summary_data, update_summary
    from src.live.live_bubble import LiveBubble

    await init_db()
    tg_user = update.effective_user
    user_id = await upsert_user(tg_user.id, tg_user.username)
    keys_list = await list_api_keys(user_id)

    # Log user message
    await add_chat_message(user_id, "user", text)

    keys = parse_keys(text)
    if not keys:
        if not keys_list:
            # Persona-guided instruction when no keys are present
            msg = (
                "Mou~ you don't have any API keys stored yet, Oni-San!\n"
                "Rikka needs at least one provider key to talk with the AIs.\n"
                "Add one with `/addkey provider:\"<key>\"` — for example:\n"
                "/addkey openrouter:\"sk-...\"  or  /addkey groq:\"gsk_...\"\n\n"
                "You can also send provider:key pairs directly in chat, e.g. ``openrouter:\"sk-...\"``."
            )
            await update.message.reply_text(msg)
            return

        # --- COMPLEXITY CHECK ---
        from src.providers.provider_pool import ProviderPool
        from src.config import Config
        cfg = Config.load()
        pool = ProviderPool()

        # Load History and Summary
        summary_data = await get_summary_data(user_id)
        summary = summary_data["summary"] if summary_data else None
        last_msg_id = summary_data["last_msg_id"] if summary_data else 0
        
        history = await get_chat_history(user_id, limit=cfg.max_context_messages, after_id=last_msg_id)

        is_complex = len(text) > 120 or any(word in text.lower() for word in ["search", "analyze", "research", "find", "who is", "what is", "calculate", "wikipedia", "fetch", "curl", "memory", "skill"])
        
        # Context construction
        context_str = f"Request: {text}"
        if summary:
            context_str = f"Summary of earlier interactions: {summary}\n\n" + context_str
        
        # history[:-1] because latest is already in 'text'
        history_parts = []
        for m in history[:-1]:
            msg_text = f"{m['role']}: {m['content']}"
            if m.get("metadata"):
                # Represent research findings naturally in history context
                agents_summary = ", ".join([f"{aid}({r.get('tool_used','analysis')})" for aid, r in m['metadata'].items()])
                msg_text += f"\n[Rikka's Research Background: {agents_summary}]"
            history_parts.append(msg_text)
            
        history_str = "\n".join(history_parts)
        if history_str:
            context_str = "Recent History:\n" + history_str + "\n\n" + context_str

        if not is_complex:
            # Direct reply for simple messages
            try:
                direct_payload = {
                    "model": cfg.default_model,
                    "messages": [
                        {"role": "system", "content": cfg.system_prompt},
                        {"role": "user", "content": context_str}
                    ]
                }
                
                priorities = cfg.default_provider_priority or ["gemini", "groq", "openrouter"]
                final_reply = None
                for p in priorities:
                    try:
                        resp = await pool.request_with_key(user_id, p, direct_payload)
                        final_reply = resp.get("output")
                        if final_reply:
                            break
                    except Exception:
                        continue
                
                if final_reply:
                    await add_chat_message(user_id, "assistant", final_reply)
                    await update.message.reply_html(final_reply)
                    if len(history) >= cfg.max_context_messages:
                        asyncio.create_task(trigger_summarization(user_id, history, summary, pool, cfg))
                else:
                    await update.message.reply_text("Mou~ I tried my best but all providers failed for a direct reply...")
                return
            except Exception as e:
                logger.exception("direct_reply_failed", error=str(e))
                await update.message.reply_text(f"Bakkaaa! Direct reply failed: {e}")
                return

        # --- ORCHESTRATION FLOW --- (if complex)
        from src.agents.rikka_agent import Orchestrator
        from src.agents.agent_bus import AgentBus
        
        # 1. Start LiveBubble
        sent = await update.message.reply_text("Rikka is consulting the fragments for a plan, Oni-San... Nipah~! 🌸")
        bubble = LiveBubble(throttle_ms=cfg.live_bubble_throttle_ms)
        async def flush_cb(text: str):
            try:
                await context.bot.edit_message_text(chat_id=sent.chat_id, message_id=sent.message_id, text=text, parse_mode='HTML')
            except Exception:
                pass
        await bubble.start(flush_cb)
        
        try:
            # 2. Generate Plan
            orchestrator = Orchestrator(cfg)
            plan = await orchestrator.generate_plan(user_id, context_str)
            bubble.update("plan", f"Plan: {plan.reasoning}")
            
            # 3. Execute Plan via AgentBus
            bus = AgentBus(plan.agents, bubble=bubble)
            initial_context = {"user_id": user_id, "message": text, "full_context": context_str}
            results = await bus.run(initial_context)
            
            # 4. Final Synthesis
            bubble.update("synthesis", "Creating final response...")
            synthesis_payload = {
                "model": cfg.default_model,
                "messages": [
                    {"role": "system", "content": cfg.system_prompt + "\n\nSYSTEM_DATA (INTERNAL): Use the following research findings to answer the user. Do NOT mention the word 'SYSTEM_DATA' or echo the JSON. Rikka's UI handles the research log separately.\n\nRESEARCH_FINDINGS:\n" + json.dumps(results, indent=2)},
                    {"role": "user", "content": f"{context_str}\n\nPrompt: {plan.final_synthesis_prompt}"}
                ]
            }
            
            priorities = cfg.default_provider_priority or ["gemini", "groq", "openrouter"]
            final_reply = None
            last_err = None
            
            for p_name in priorities:
                try:
                    resp = await pool.request_with_key(user_id, p_name, synthesis_payload)
                    final_reply = resp.get("output")
                    if final_reply:
                        break
                except Exception as e:
                    logger.warning("synthesis_provider_failed", provider=p_name, error=str(e))
                    last_err = str(e)
                    continue
            
            await bubble.stop()
            
            if final_reply:
                # 5. Extract and hide JSON findings from the user
                # We look for the JSON block and remove it from the final_reply
                extracted_findings = results # default to existing results
                
                json_match = re.search(r"Internal Research Findings:?\s*(\{.*?\})", final_reply, re.DOTALL)
                if json_match:
                    try:
                        # If the LLM generated its own JSON block, we can parse it
                        # but we primarily use the 'results' from our AgentBus
                        final_reply = final_reply.replace(json_match.group(0), "").strip()
                    except Exception:
                        pass

                # Final cleanup of any trailing labels
                for marker in ["RESEARCH_FINDINGS", "SYSTEM_DATA", "Internal Research Findings"]:
                    if marker in final_reply:
                        final_reply = final_reply.split(marker)[0].strip()
                
                # Format findings as a feature log (UI ONLY)
                findings_block = "\n\n<b>📋 Research Log:</b>\n"
                for agent_id, res in results.items():
                    tool = res.get("tool_used", "analysis")
                    output_preview = res.get("output", "Done")
                    # Cleanup for preview
                    output_preview = (output_preview[:150] + "...") if len(output_preview) > 150 else output_preview
                    findings_block += f"• <b>{agent_id}</b> (<i>{tool}</i>): {output_preview}\n"
                
                full_response = final_reply + findings_block
                
                # Store message WITH metadata (the findings)
                await add_chat_message(user_id, "assistant", final_reply, metadata=results)
                
                try:
                    await context.bot.edit_message_text(chat_id=sent.chat_id, message_id=sent.message_id, text=full_response, parse_mode='HTML')
                except Exception:
                    await context.bot.edit_message_text(chat_id=sent.chat_id, message_id=sent.message_id, text=full_response)
                
                if len(history) >= cfg.max_context_messages:
                    asyncio.create_task(trigger_summarization(user_id, history, summary, pool, cfg))
            else:
                msg = "Mou~ I couldn't synthesize a final answer, but the agents finished their tasks!"
                if last_err: msg += f"\n\nLast error: {last_err}"
                await context.bot.edit_message_text(chat_id=sent.chat_id, message_id=sent.message_id, text=msg)

        except Exception as e:
            logger.exception("orchestration_failed", error=str(e))
            if 'bubble' in locals():
                await bubble.stop()
            await update.message.reply_text(f"Bakkaaa! Something went wrong with the plan: {e}")
        
        return

    # --- KEY SUBMISSION FLOW ---
    sent = await update.message.reply_text("Rikka is checking these keys across the fragments, Oni-San...\n")
    bubble = LiveBubble(throttle_ms=800)

    async def flush_cb_keys(text: str):
        try:
            await context.bot.edit_message_text(chat_id=sent.chat_id, message_id=sent.message_id, text=text)
        except Exception:
            pass

    await bubble.start(flush_cb_keys)

    from src.providers.provider_pool import ProviderPool
    pool = ProviderPool()

    results = []
    for provider, raw in keys.items():
        bubble.update(provider, "storing...")
        try:
            key_id = await add_api_key(user_id, provider, raw)
            bubble.update(provider, "stored; validating...")
            try:
                ok = await pool.get_healthy_key(user_id, provider)
                if ok:
                    results.append((provider, key_id, "valid"))
                    bubble.update(provider, "validated — key OK")
                else:
                    results.append((provider, key_id, "invalid"))
                    bubble.update(provider, "validation failed — check key")
            except Exception as e:
                results.append((provider, key_id, f"validation error: {e}"))
                bubble.update(provider, f"validation error: {e}")
        except Exception as e:
            bubble.update(provider, f"error storing key: {e}")
            results.append((provider, None, f"error: {e}"))

    text_lines = []
    for provider, kid, status in results:
        text_lines.append(f"{provider}: {status}")
    await bubble.stop()
    await context.bot.edit_message_text(chat_id=sent.chat_id, message_id=sent.message_id, text="Key submission results:\n" + "\n".join(text_lines))

async def trigger_summarization(user_id: int, history: list, old_summary: str | None, pool, cfg):
    from src.db.chat_store import update_summary
    logger.info("triggering_summarization", user_id=user_id)
    
    # Context includes the metadata/findings for high-fidelity summary
    history_text = ""
    for m in history:
        history_text += f"{m['role']}: {m['content']}"
        if m.get("metadata"):
            history_text += f"\n(Research Findings: {json.dumps(m['metadata'])})"
        history_text += "\n"

    prompt = (
        "Summarize the following interaction history into a 'Permanent Knowledge State'.\n"
        "Include:\n"
        "1. Important facts about the user (Oni-San).\n"
        "2. Key technical findings and research results from the agents.\n"
        "3. Current goals or pending tasks.\n\n"
        f"Old Knowledge State: {old_summary or 'None'}\n\n"
        f"New History:\n{history_text}"
    )
    
    payload = {"model": cfg.default_model, "messages": [{"role": "system", "content": "You are Rikka's High-Fidelity Knowledge Processor. Your summary must be dense with facts and findings."}, {"role": "user", "content": prompt}]}
    try:
        priorities = cfg.default_provider_priority or ["gemini", "groq", "openrouter"]
        for p in priorities:
            try:
                resp = await pool.request_with_key(user_id, p, payload)
                new_summary = resp.get("output")
                if new_summary:
                    await update_summary(user_id, new_summary, history[-1]['id'])
                    return
            except Exception: continue
    except Exception as e:
        logger.error("summarization_failed", user_id=user_id, error=str(e))

def build_application(config: Config):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("addkey", addkey_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("broadcast", broadcast_handler))
    app.add_handler(CommandHandler("delete_me", delete_me_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, key_submission_handler))
    return app


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    from src.db.key_store import delete_user_by_telegram_id

    if data == "confirm_delete":
        tg_id = query.from_user.id
        deleted = await delete_user_by_telegram_id(tg_id)
        if deleted:
            await query.edit_message_text("All your data has been deleted. Rikka will miss you, Oni-San.")
        else:
            await query.edit_message_text("No data found for your account.")
    else:
        await query.edit_message_text("Deletion cancelled.")


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin command: show basic stats
    from src.db.key_store import list_api_keys, upsert_user
    tg_user = update.effective_user
    user_id = await upsert_user(tg_user.id, tg_user.username)
    
    keys = await list_api_keys(user_id)
    active_keys = [k for k in keys if not k['is_blacklisted']]
    
    msg = (
        f"<b>📊 Rikka's Internal Status:</b>\n"
        f"• Your ID: <code>{tg_user.id}</code>\n"
        f"• Total Keys: {len(keys)}\n"
        f"• Healthy Keys: {len(active_keys)}\n"
        f"• Fragments Aligned: True\n"
        f"• Current Soul: {Config.load().default_model}"
    )
    await update.message.reply_html(msg)


async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner = os.environ.get("OWNER_USER_ID")
    if not owner or str(update.effective_user.id) != str(owner):
        logger.warning("unauthorized_broadcast_attempt", user_id=update.effective_user.id)
        await update.message.reply_text("Bakkaaa!! Only my master can broadcast!")
        return
    
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /broadcast message")
        return

    from src.db.connection import get_db
    async with get_db() as db:
        cursor = await db.execute("SELECT telegram_user_id FROM users")
        users = await cursor.fetchall()
    
    count = 0
    for user in users:
        try:
            # Skip sending to self if you want, but usually masters want to see the broadcast too
            await context.bot.send_message(chat_id=user[0], text=f"<b>📣 Message from Rikka-sama:</b>\n\n{text}", parse_mode='HTML')
            count += 1
            await asyncio.sleep(0.05) # Rate limiting
        except Exception as e:
            logger.error("broadcast_send_failed", user_id=user[0], error=str(e))
            continue
            
    await update.message.reply_text(f"Nipah~! Broadcast sent to {count} users!")


def main():
    load_dotenv()
    config = Config.load()

    app = build_application(config)
    # Start background tasks (unblacklist scheduler)
    try:
        import asyncio
        from src.providers.unblacklist_scheduler import unblacklist_loop
        from src.scheduler import start_scheduler

        loop = asyncio.get_event_loop()
        # start APScheduler scheduled jobs
        try:
            start_scheduler(config)
        except Exception:
            pass
        # keep existing lightweight unblacklist loop as fallback
        loop.create_task(unblacklist_loop())
    except Exception:
        pass

    print("Starting Rikka (polling). Press Ctrl-C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
