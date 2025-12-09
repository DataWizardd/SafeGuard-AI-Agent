import streamlit as st
import os
import time
from agent_graph import app_graph

st.set_page_config(page_title="SafeGuard-AI", layout="wide")

st.title("🛡️ SafeGuard-AI (Smart Factory Safety)")
st.caption("제조 현장 작업 허가 및 위험성 평가 자동화 시스템")

# 스타일 커스텀 (에이전트 박스 디자인)
st.markdown("""
<style>
    .agent-box {
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border: 1px solid #e0e0e0;
    }
    .agent-title {
        font-weight: bold;
        font-size: 1.1em;
        margin-bottom: 5px;
    }
</style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("is_html"):
            st.markdown(msg["content"], unsafe_allow_html=True)
        else:
            st.write(msg["content"])

if prompt := st.chat_input("작업 내용을 입력하세요 (예: 12시 30분에 톨루엔 탱크 배관 용접 작업 예정)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        # 전체 프로세스 상태창
        status_container = st.container(border=True)
        status_text = status_container.empty()
        
        inputs = {"user_input": prompt, "messages": [], "context": "", "risk_score": 0, "needs_more_info": False}
        final_res = None
        pdf_path = None
        
        try:
            # LangGraph 스트리밍 시작
            status_text.info("🚀 안전 분석 프로세스를 시작합니다...")
            
            for output in app_graph.stream(inputs):
                for key, value in output.items():
                    
                    # 1. Coordinator (조정관)
                    if key == "coordinator":
                        with status_container:
                            if value.get("needs_more_info"):
                                st.warning("🤖 **Main Coordinator:** 정보 부족 감지! 추가 질문을 생성합니다.")
                                final_res = value['messages'][0]
                            else:
                                st.success("🤖 **Main Coordinator:** 작업 의도 파악 완료. 규정 검색 에이전트를 호출합니다.")
                                time.sleep(0.5) # 시각적 효과를 위한 짧은 대기

                    # 2. Regulation Agent (규정 검색) - 디테일하게 보여주기
                    elif key == "regulation_finder":
                        with status_container:
                            st.info("📚 **Regulation Agent:** 관련 법령 및 사내 규정을 검색했습니다.")
                            
                            # 검색된 문서를 파싱해서 깔끔하게 보여줌
                            raw_context = value['context']
                            docs = raw_context.split("\n\n---\n\n") # 아까 넣은 구분자로 쪼개기
                            
                            with st.expander(f"🔍 검색된 근거 자료 ({len(docs)}건) 상세보기"):
                                for i, doc in enumerate(docs):
                                    # 파일명과 내용 분리
                                    lines = doc.split("\n")
                                    source_line = lines[0] if lines else "출처 미상"
                                    content_text = "\n".join(lines[1:])
                                    
                                    st.markdown(f"**{i+1}. {source_line}**")
                                    st.caption(content_text[:200] + "..." if len(content_text) > 200 else content_text)
                                    st.divider()

                    # 3. Risk Analyst (위험 분석가)
                    elif key == "risk_analyst":
                        score = value.get('risk_score', 0)
                        # context에 아까 만든 final_report가 붙어있음. 그걸 파싱해서 보여주거나,
                        # 더 깔끔하게 하려면 agent_graph에서 값을 따로 넘겨주는 게 좋지만,
                        # 지금은 간편하게 context의 뒷부분(리포트)을 활용해 UI를 그림.
                        
                        # 리포트 추출 (간이 방식)
                        report_content = value['context'].split("**🎯 Fine-Kinney 위험성 평가 결과**")[1]
                        
                        with status_container:
                            if score >= 160:
                                st.error(f"⚠️ **Risk Analyst:** 고위험 판정! (Score: {score})")
                            else:
                                st.success(f"✅ **Risk Analyst:** 허용 가능 범위 (Score: {score})")
                            
                            # 수식과 상세 내용을 카드 안에 예쁘게 출력
                            st.markdown("---")
                            st.markdown("**🎯 정량적 위험성 평가 (Fine-Kinney)**")
                            st.markdown(report_content, unsafe_allow_html=True)
                            time.sleep(0.5)

                    # 4. Admin Agent (행정관)
                    elif key == "admin_agent":
                        with status_container:
                            st.write("📝 **Admin Agent:** 최종 결과 보고서 및 PDF를 생성 중입니다...")
                        final_res = value.get('final_output', "결과 생성 실패")
                        pdf_path = value.get('pdf_path', None)

            status_text.empty() # 맨 위 상태 메시지 지우기
            
        except Exception as e:
            st.error(f"에러 발생: {e}")

        # 최종 결과 카드 출력
        if final_res:
            res_container = st.container(border=True)
            res_container.markdown(final_res)
            
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as file:
                    res_container.download_button(
                        label="📄 정식 작업허가서(PDF) 다운로드",
                        data=file,
                        file_name=os.path.basename(pdf_path),
                        mime="application/pdf"
                    )
            
            st.session_state.messages.append({"role": "assistant", "content": final_res})