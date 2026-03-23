from langchain.embeddings import init_embeddings
import os
from dotenv import load_dotenv
load_dotenv()
langchain_embedding_model = init_embeddings(model=os.getenv("OPENAI_EMBEDDING_MODEL"),
                                                    provider="ollama",
                                                    #api_key=os.getenv("OPENAI_API_KEY"),
                                                    base_url="http://localhost:11434",
                                                    )

print(langchain_embedding_model.embed_query("testing"))