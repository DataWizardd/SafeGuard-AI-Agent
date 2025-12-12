import os
import shutil
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# 환경 변수 로드
load_dotenv()

DB_PATH = "./faiss_db"


def get_retriever():

    print("🧠 임베딩 모델 로드 중 (BAAI/bge-m3)...")
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    # 1. 이미 만들어진 DB가 있는지 확인
    if os.path.exists(DB_PATH):
        print("💾 기존 벡터 DB를 로드합니다...")
        try:
            vectorstore = FAISS.load_local(
                DB_PATH, embeddings, allow_dangerous_deserialization=True
            )

            return vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 6},
            )

            # mmr? (실험해보기)
            # return vectorstore.as_retriever(
            #     search_type="mmr",
            #     search_kwargs={"k": 10, "fetch_k": 20},
            # )

        except Exception as e:
            print(f"⚠️ 기존 DB 로드 실패 : {e}")
            print("🗑️ 기존 DB를 삭제하고 새로 생성합니다.")
            shutil.rmtree(DB_PATH)  # 폴더 삭제

    # 2. 없으면 새로 생성
    print("🔄 새로운 벡터 DB를 생성합니다...")
    if not os.path.exists("./data"):
        os.makedirs("./data")
        print("⚠️ 'data' 폴더가 비어있습니다. PDF 파일을 넣어주세요.")
        return None

    documents = []
    for file in os.listdir("./data"):
        if file.endswith(".pdf"):
            print(f"   - 로딩 중: {file}")
            loader = PyPDFLoader(f"./data/{file}")
            docs = loader.load()
            documents.extend(docs)

    if not documents:
        print("❌ 로드할 PDF 파일이 없습니다.")
        return None

    # 3. 텍스트 분할 (Chunking)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    splits = text_splitter.split_documents(documents)

    # 4. 벡터 저장소 생성 및 저장
    print("vectors 생성 중... (시간이 조금 걸릴 수 있습니다)")
    vectorstore = FAISS.from_documents(splits, embeddings)
    vectorstore.save_local(DB_PATH)
    print("🎉 DB 생성 및 저장 완료!")

    # 리턴 시에도 동일한 검색 조건 적용
    return vectorstore.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={"score_threshold": 0.4, "k": 8},
    )


if __name__ == "__main__":
    get_retriever()
