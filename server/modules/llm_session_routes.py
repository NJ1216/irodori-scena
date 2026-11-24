from server.registry import deps


@deps.app.get("/api/llm/session-usage")
def get_llm_session_usage():
    return deps.session_usage()


@deps.app.post("/api/llm/session-usage/reset")
def reset_llm_session_usage():
    return deps.reset_session_usage()


deps.register(__name__, ["get_llm_session_usage", "reset_llm_session_usage"])
