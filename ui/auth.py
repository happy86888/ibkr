"""
Password gate for Streamlit Cloud deployment.

Reads passwords from .streamlit/secrets.toml:
  passwords = ["yourpw1", "yourpw2", "friend1pw"]

Or from environment variable APP_PASSWORDS (comma-separated).

If no passwords configured AND not detected as cloud → skip auth (local dev).
"""
import os
import streamlit as st


def get_valid_passwords():
    """Load passwords from secrets or env."""
    try:
        if "passwords" in st.secrets:
            pwds = st.secrets["passwords"]
            if isinstance(pwds, list):
                return list(pwds)
            return [str(pwds)]
    except Exception:
        pass

    env_pwds = os.environ.get("APP_PASSWORDS", "")
    if env_pwds:
        return [p.strip() for p in env_pwds.split(",") if p.strip()]

    return []


def is_cloud() -> bool:
    return any(
        os.environ.get(k) for k in (
            "STREAMLIT_SHARING_MODE", "STREAMLIT_CLOUD",
            "RAILWAY_ENVIRONMENT", "RENDER", "FLY_APP_NAME",
        )
    ) or os.environ.get("HOSTNAME", "").startswith("streamlit-")


def check_password() -> bool:
    """Show password gate if needed. Returns True when authenticated."""
    valid = get_valid_passwords()

    # Local dev with no passwords: skip
    if not valid and not is_cloud():
        return True

    # Cloud with no passwords: warn
    if not valid and is_cloud():
        st.error(
            "⚠️ **此 app 部署在雲端但未設定密碼**\n\n"
            "請到 Streamlit Cloud → App settings → Secrets 加入：\n\n"
            '```\npasswords = ["your_password"]\n```'
        )
        st.stop()

    if st.session_state.get("authenticated"):
        return True

    # Render login screen
    st.markdown(
        "<div style='text-align:center; padding: 3rem 0 1rem 0;'>"
        "<h1>📈 Covered Call System</h1>"
        "<p style='color: #888;'>Authorized access only</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("login"):
            pwd = st.text_input("Password", type="password",
                                 placeholder="Enter password",
                                 label_visibility="collapsed")
            ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if ok:
                if pwd in valid:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("❌ Wrong password")
    st.stop()
    return False


def logout_button():
    """Add a logout button to wherever it's called."""
    if st.session_state.get("authenticated"):
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.pop("authenticated", None)
            st.rerun()
