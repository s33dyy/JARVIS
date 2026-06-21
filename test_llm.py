import sys
import time
sys.path.append("/Users/pratikchoudhuri/Documents/antigravity/goofy-bose/OpenJarvis")
from jarvis_llm import ask_llm

start = time.time()
print("Asking LLM...")
res = ask_llm("Say hello", model_type="fast")
print("Response:", res)
print("Time taken:", time.time() - start)
