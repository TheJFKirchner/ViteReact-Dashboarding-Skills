"""TEST ONLY: a scripted stand-in for Claude, used when DASH_AGENT_FAKE=1.

It calls the same tools the real agent gets, so tests exercise the real guards, preview,
render checks and keep/discard without spending tokens. Message format:

    FAKE: [{"edit": ["old text", "new text"]}, {"look": true}, {"say": "Done."}, {"usage": {...}},
          {"controls": [{"kind": "color", "label": "Line color", "anchor": "...", "value": "f.color(0)"}]}]

Card:   {"edit": ["old", "new"]} (chart code), {"commentary": "new text"}, {"look": true},
        {"controls": [{... "anchor", "value"}]} (bound to card code)
Page:   {"text": ["title", "New title"]}, {"css": ["old css or empty", "new css"]}
Theme:  {"theme": [{"path": "colors.accent", "value": "#FF8800"}]},
        {"controls": [{"kind": "color", "label": "Accent", "path": "colors.accent"}]} (bound to a theme path)
Shared component: {"component": ["KpiTile", "old", "new"]}
Layout: {"arrange": {"tabs": [{"tab": "overview", "cards": ["a_summary", {"id": "g_x", "size": "half"}]}],
                     "tab_order": [...], "hide": [...]}}
Other card: {"open": ["b_pmpm_trend", "make the line thicker"]}
Reports tab (report builder / instructions; v2 report format):
        {"report": {"title": "...", "cards": [...], "filters": {"region": {"mode": "fixed", "value": "East"}}}},
        {"report": {"combinations": {"except": [{"line_of_business": "Medicaid"}]}, "parameters": {"as_of": "2026-07-31"}}},
        {"ask": ["How should Region work?", ["Viewer can change", "Fixed: East"], false]}, {"save": ["name", false]}
Any:    {"view": "card" | "commentary" | "page" | "theme" | "layout"},
        {"request": "can I change the color?", "clicked": {"series": "..."}} (what the user asked + clicked, for the color rules)

Returns (reply, usage) like the real agent; usage is None unless a "usage" step is given.
"""
import json


async def run_fake(session, message: str) -> str:
    if not message.startswith("FAKE:"):
        return "(test mode) Send FAKE: [steps] - the real model is off (DASH_AGENT_FAKE=1).", None
    log, usage = [], None
    for step in json.loads(message[5:]):
        if "edit" in step:
            r = await session.tool_edit(*step["edit"])
            log.append(("edit error: " if r.get("is_error") else "edit: ") + r["content"][0]["text"])
        elif "look" in step:
            r = await session.tool_look()
            log.append("look: image" if r["content"][0]["type"] == "image" else "look: " + r["content"][0]["text"])
        elif "view" in step:
            what = step["view"] if isinstance(step["view"], str) else "card"
            log.append(f"view: {len((await session.tool_view(what))['content'][0]['text'])} chars")
        elif "commentary" in step:
            r = await session.tool_commentary(step["commentary"])
            log.append(("commentary error: " if r.get("is_error") else "commentary: ") + r["content"][0]["text"])
        elif "component" in step:
            r = await session.tool_edit_component(*step["component"])
            log.append(("component error: " if r.get("is_error") else "component: ") + r["content"][0]["text"])
        elif "request" in step:
            session.note_request(step["request"], step.get("clicked"))
        elif "say" in step:
            log.append(step["say"])
        elif "usage" in step:
            usage = step["usage"]
        elif "text" in step:
            r = await session.tool_set_text(*step["text"])
            log.append(("text error: " if r.get("is_error") else "text: ") + r["content"][0]["text"])
        elif "css" in step:
            r = await session.tool_edit_styles(*step["css"])
            log.append(("css error: " if r.get("is_error") else "css: ") + r["content"][0]["text"])
        elif "theme" in step:
            r = await session.tool_set_theme(step["theme"])
            log.append(("theme error: " if r.get("is_error") else "theme: ") + r["content"][0]["text"])
        elif "arrange" in step:
            spec = step["arrange"]
            r = await session.tool_arrange(spec.get("tabs"), spec.get("tab_order"), spec.get("hide"))
            log.append(("arrange error: " if r.get("is_error") else "arrange: ") + r["content"][0]["text"])
        elif "open" in step:
            r = await session.tool_open_card(*step["open"])
            log.append(("open error: " if r.get("is_error") else "open: ") + r["content"][0]["text"])
        elif "report" in step:
            r = await session.tool_set_report(step["report"])
            log.append(("report error: " if r.get("is_error") else "report: ") + r["content"][0]["text"])
        elif "ask" in step:
            r = await session.tool_ask(*step["ask"])
            log.append(("ask error: " if r.get("is_error") else "ask: ") + r["content"][0]["text"])
        elif "save" in step:
            r = await session.tool_save(*step["save"])
            log.append(("save error: " if r.get("is_error") else "save: ") + r["content"][0]["text"])
        elif "controls" in step:
            r = await session.tool_offer(step["controls"])
            log.append(("controls error: " if r.get("is_error") else "controls: ") + r["content"][0]["text"])
    return " | ".join(log), usage
