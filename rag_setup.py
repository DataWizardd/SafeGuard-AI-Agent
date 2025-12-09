import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

# 환경 변수 로드
load_dotenv()

DB_PATH = "./faiss_db"  # 벡터 DB 저장 경로

def get_retriever():
    """
    저장된 FAISS DB가 있으면 불러오고, 없으면 새로 만듭니다.
    """
    # chunk_size=100 추가 (한 번에 100개씩만 쪼개서 보냄)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", chunk_size=100)

    # 1. 이미 만들어진 DB가 있는지 확인
    if os.path.exists(DB_PATH):
        print("💾 기존 벡터 DB를 로드합니다...")
        vectorstore = FAISS.load_local(DB_PATH, embeddings, allow_dangerous_deserialization=True)
        return vectorstore.as_retriever(search_kwargs={"k": 4}) # 관련 문서 4개 검색

    # 2. 없으면 새로 생성 (PDF 로드)
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
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)
    splits = text_splitter.split_documents(documents)

    # 4. 벡터 저장소 생성 및 저장
    vectorstore = FAISS.from_documents(splits, embeddings)
    vectorstore.save_local(DB_PATH)
    print("🎉 DB 생성 및 저장 완료!")

    return vectorstore.as_retriever(search_kwargs={"k": 4})

# 이 파일을 직접 실행하면 DB를 미리 빌드할 수 있습니다.
if __name__ == "__main__":
    get_retriever()