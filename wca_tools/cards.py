import streamlit as st


def render_milestone_cards(milestones: list[dict]) -> None:
    cards = "".join(
        f'<div class="milestone-card">'
        f'<div class="milestone-num">🏆 {h["Competitions"]}</div>'
        f'<div class="milestone-name">{h["Name"]}</div>'
        f'<div class="milestone-id">{h["WCA ID"]}</div>'
        f"</div>"
        for h in sorted(milestones, key=lambda x: x["Competitions"], reverse=True)
    )
    st.html(
        f"""
    <style>
      .milestone-grid {{display:flex;flex-wrap:wrap;gap:12px;}}
      .milestone-card {{background:#f8f9fa;border-radius:10px;padding:12px 16px;min-width:160px;}}
      .milestone-num {{font-size:22px;font-weight:700;color:#333;}}
      .milestone-name {{font-size:14px;font-weight:600;margin-top:4px;}}
      .milestone-id {{font-size:12px;color:#888;margin-top:2px;}}
    </style>
    <div class="milestone-grid">{cards}</div>
    """
    )


def render_birthday_cards(birthdays: list[dict], fmt_birthday_fn) -> None:
    cards = "".join(
        f'<div class="bd-card">'
        f'<div class="bd-icon">🎂</div>'
        f'<div class="bd-name">{b["Name"]}</div>'
        f'<div class="bd-date">{b["Birthday"]}</div>'
        f'<div class="bd-when">{fmt_birthday_fn(b["Days"])}</div>'
        f"</div>"
        for b in sorted(birthdays, key=lambda x: x["Days"])
    )
    st.html(
        f"""
    <style>
      .bd-grid {{display:flex;flex-wrap:wrap;gap:12px;}}
      .bd-card {{background:#fff8f0;border-radius:10px;padding:12px 16px;
                min-width:150px;border:1px solid #ffe0b2;}}
      .bd-icon {{font-size:22px;}}
      .bd-name {{font-size:14px;font-weight:600;margin-top:4px;}}
      .bd-date {{font-size:12px;color:#888;}}
      .bd-when {{font-size:12px;color:#e65100;font-weight:500;margin-top:2px;}}
    </style>
    <div class="bd-grid">{cards}</div>
    """
    )
