from langchain_ollama import OllamaLLM
from langchain_ollama import OllamaEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_classic.chains import RetrievalQA


# 1 Load document
loader = PyPDFLoader("data/document.pdf")
docs = loader.load()

# 2 Split document
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50
)

documents = text_splitter.split_documents(docs)

# 3 Embeddings using Ollama
embeddings = OllamaEmbeddings(model="nomic-embed-text")

# 4 Vector store
vector_db = Chroma.from_documents(
    documents,
    embedding=embeddings,
    persist_directory="./chroma_db"
)

# 5 Retriever
retriever = vector_db.as_retriever()

# 6 LLM using Ollama
llm = OllamaLLM(model="qwen2:0.5b")

# 7 RAG chain
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=retriever
)

# 8 Ask question
query = input("Enter the Query regarding the document: ")
result = qa_chain.invoke(query)

print(result)
