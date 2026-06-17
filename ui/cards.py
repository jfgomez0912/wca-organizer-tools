import streamlit as st


def render_hito_cards(hitos: list[dict]) -> None:
    cards = "".join(
        f'<div class="hito-card">'
        f'<div class="hito-num">🏆 {h["Competencias"]}</div>'
        f'<div class="hito-name">{h["Nombre"]}</div>'
        f'<div class="hito-id">{h["WCA ID"]}</div>'
        f"</div>"
        for h in sorted(hitos, key=lambda x: x["Competencias"], reverse=True)
    )
    st.html(
        f"""
    <style>
      .hito-grid {{display:flex;flex-wrap:wrap;gap:12px;}}
      .hito-card {{background:#f8f9fa;border-radius:10px;padding:12px 16px;min-width:160px;}}
      .hito-num {{font-size:22px;font-weight:700;color:#333;}}
      .hito-name {{font-size:14px;font-weight:600;margin-top:4px;}}
      .hito-id {{font-size:12px;color:#888;margin-top:2px;}}
    </style>
    <div class="hito-grid">{cards}</div>
    """
    )


def render_birthday_cards(birthdays: list[dict], fmt_birthday_fn) -> None:
    cards = "".join(
        f'<div class="bd-card">'
        f'<div class="bd-icon">🎂</div>'
        f'<div class="bd-name">{b["Nombre"]}</div>'
        f'<div class="bd-date">{b["Cumpleaños"]}</div>'
        f'<div class="bd-when">{fmt_birthday_fn(b["Días"])}</div>'
        f"</div>"
        for b in sorted(birthdays, key=lambda x: x["Días"])
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
