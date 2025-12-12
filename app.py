import streamlit as st
import os
import uuid
import phoenix as px
from phoenix.otel import register


# ---------------------------------------------------------
# [Phoenix 설정]
# ---------------------------------------------------------
@st.cache_resource
def setup_phoenix():
    session = px.launch_app()
    register(
        project_name="SafeGuard-AI",
        endpoint="http://localhost:6006/v1/traces",
        auto_instrument=True,
    )
    print(f"🦅 Phoenix가 실행되었습니다: {session.url}")
    return session


phoenix_session = setup_phoenix()

# ---------------------------------------------------------
# [그래프 로드]
# ---------------------------------------------------------
from agent_graph import app_graph

st.set_page_config(page_title="SafeGuard-AI", layout="wide")
st.title("🛡️ SafeGuard-AI")
st.caption("제조 현장 작업 허가 및 위험성 평가 자동화 시스템")

# ---------------------------------------------------------
# [세션 관리 로직]
# ---------------------------------------------------------
if "sessions" not in st.session_state:
    st.session_state.sessions = {}

if "current_session_id" not in st.session_state:
    new_id = str(uuid.uuid4())
    st.session_state.current_session_id = new_id
    st.session_state.sessions[new_id] = []


def start_new_chat():
    """새로운 채팅 세션을 생성하고 전환"""
    new_id = str(uuid.uuid4())
    st.session_state.current_session_id = new_id
    st.session_state.sessions[new_id] = []


# 현재 선택된 세션의 메시지 리스트 가져오기
current_messages = st.session_state.sessions[st.session_state.current_session_id]

# ---------------------------------------------------------
# [사이드바]
# ---------------------------------------------------------
with st.sidebar:
    if st.button("➕ 새 채팅 시작", use_container_width=True, type="primary"):
        start_new_chat()
        st.rerun()

    st.divider()

    st.markdown("### 🕒 대화 히스토리")
    session_ids = list(st.session_state.sessions.keys())[::-1]

    for sess_id in session_ids:
        msgs = st.session_state.sessions[sess_id]
        if not msgs:
            continue

        first_user_msg = next(
            (m["content"] for m in msgs if m["role"] == "user"), "새로운 대화"
        )
        btn_label = (
            first_user_msg[:15] + "..." if len(first_user_msg) > 15 else first_user_msg
        )

        if st.button(btn_label, key=sess_id, use_container_width=True):
            st.session_state.current_session_id = sess_id
            st.rerun()

    st.divider()
    st.header("🔧 개발자 도구")
    if phoenix_session:
        st.link_button("🚀 추적 대시보드 열기", phoenix_session.url)

# ---------------------------------------------------------
# [메인 채팅 UI]
# ---------------------------------------------------------

# 이전 대화 출력
for msg in current_messages:
    with st.chat_message(msg["role"]):
        if msg.get("is_html"):
            st.markdown(msg["content"], unsafe_allow_html=True)
        else:
            st.write(msg["content"])

# 사용자 입력 처리
if prompt := st.chat_input("작업 내용을 입력하세요..."):

    # 1. 사용자 메시지 저장
    st.session_state.sessions[st.session_state.current_session_id].append(
        {"role": "user", "content": prompt}
    )

    with st.chat_message("user"):
        st.write(prompt)

    # 2. AI 처리
    with st.chat_message("assistant"):
        status_container = st.container(border=True)
        status_text = status_container.empty()

        # 기억력 20턴으로 확장 (현재 세션 기준)
        chat_history_text = ""

        for msg in st.session_state.sessions[st.session_state.current_session_id][-20:]:
            role_name = "User" if msg["role"] == "user" else "AI"
            chat_history_text += f"{role_name}: {msg['content']}\n"

        inputs = {
            "user_input": prompt,
            "chat_history": chat_history_text,  # 확장된 기억력 전달
            "messages": [],
            "context": "",
            "risk_score": 0,
            "needs_more_info": False,
        }

        final_res = None
        pdf_path = None
        risk_score_val = 0

        try:
            status_text.info("🚀 안전 분석 프로세스를 시작합니다...")

            for output in app_graph.stream(inputs):
                for key, value in output.items():
                    if key == "coordinator":
                        with status_container:
                            if value.get("needs_more_info"):
                                st.warning(
                                    "🤖 **Main Orchestrator:** 정보 부족 감지! 추가 질문을 생성합니다."
                                )
                                final_res = value["messages"][0]
                            else:
                                st.success(
                                    "🤖 **Main Orchestrator:** 작업 의도 파악 완료."
                                )

                    elif key == "regulation_finder":
                        with status_container:
                            st.info("📚 **Regulation Agent:** 관련 규정 검색 완료.")
                            raw_context = value["context"]
                            if "\n\n---\n\n" in raw_context:
                                docs = raw_context.split("\n\n---\n\n")
                            else:
                                docs = [raw_context]

                            with st.expander(f"🔍 근거 자료 ({len(docs)}건)"):
                                for i, doc in enumerate(docs):
                                    lines = doc.split("\n")
                                    st.caption(f"**{i+1}. {lines[0]}**")

                    elif key == "risk_analyst":
                        score = value.get("risk_score", 0)
                        risk_score_val = score
                        try:
                            if (
                                "**🎯 Fine-Kinney 위험성 평가 결과**"
                                in value["context"]
                            ):
                                report_content = value["context"].split(
                                    "**🎯 Fine-Kinney 위험성 평가 결과**"
                                )[1]
                            else:
                                report_content = ""
                        except:
                            report_content = ""

                        with status_container:
                            if score >= 160:
                                st.error(
                                    f"⚠️ **Risk Analyst:** 고위험 판정 (Score: {score})"
                                )
                            else:
                                st.success(
                                    f"✅ **Risk Analyst:** 허용 범위 (Score: {score})"
                                )
                            st.markdown(report_content, unsafe_allow_html=True)

                    elif key == "admin_agent":
                        with status_container:
                            st.write("📝 **Admin Agent:** 최종 문서 생성 중...")
                        final_res = value.get("final_output", "결과 생성 실패")
                        pdf_path = value.get("pdf_path", None)

            status_text.empty()

        except Exception as e:
            st.error(f"에러 발생: {e}")

        if final_res:
            res_container = st.container(border=True)
            res_container.markdown(final_res)

            if risk_score_val >= 70:
                st.info(
                    "💡 **Tip:** 안전 조치(환기, 감시인 배치, 접지 등)를 추가하여 다시 입력하면 위험도가 재평가됩니다."
                )

            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as file:
                    res_container.download_button(
                        label="📄 작업허가서(PDF) 다운로드",
                        data=file,
                        file_name=os.path.basename(pdf_path),
                        mime="application/pdf",
                    )

            st.session_state.sessions[st.session_state.current_session_id].append(
                {"role": "assistant", "content": final_res, "is_html": True}
            )
