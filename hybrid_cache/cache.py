import os
import json
from google import genai
from google.genai import types
import pydantic
from typing import Optional

# Initialize Google GenAI client
api_key = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)

class CacheDecision(pydantic.BaseModel):
    decision: str  # "full", "partial", or "none"
    matching_query: Optional[str] = None
    partial_answer: Optional[str] = None

def get_llm_decision(query: str, cache_dict: dict) -> CacheDecision:
    """
    Asks the LLM to decide whether the query can be answered fully or partially by the cache,
    or if it is a cache miss.
    """
    prompt = f"""You are a caching decision coordinator. Your job is to determine if a new user query can be answered using a cache of previously answered queries and responses.

New User Query: "{query}"

Cached Queries and Responses (as a dictionary of query: response):
{json.dumps(cache_dict, indent=2)}

Please evaluate the New User Query against the Cache and decide:
1. "full": If a cached query is semantically equivalent to the New User Query (shares the same intent and context) such that its response completely answers the new query.
2. "partial": If a cached query contains information that partially answers the New User Query, but the user is asking for additional information or a modification that is not in the cached response. Extract the relevant partial answer that can be reused.
3. "none": If no cached query is semantically related or useful to answer the New User Query.

You must respond in JSON format matching the schema:
- decision: "full", "partial", or "none"
- matching_query: The exact string key of the matching query from the cache (only if decision is "full" or "partial").
- partial_answer: A string representing the partial information extracted from the cached response (only if decision is "partial").
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CacheDecision,
                temperature=0.0
            )
        )
        if response.parsed:
            return response.parsed
    except Exception as e:
        print(f"Error during cache decision LLM call: {e}")
    return CacheDecision(decision="none")

def before_agent_hybrid_cache_callback(callback_context) -> Optional[types.Content]:
    """
    Before Agent Callback: Evaluates cache using the LLM.
    Handles full hit (returns cached answer) and partial hit (injects partial context to user prompt).
    """
    # Extract user query
    query = ""
    if callback_context.user_content and callback_context.user_content.parts:
        query = "".join(part.text for part in callback_context.user_content.parts if part.text)
        
    if not query.strip():
        return None
        
    # Store original query to ensure we save it properly in the after callback
    callback_context.state["temp:original_query"] = query
    
    # Retrieve cache dictionary from session state
    cache_dict = callback_context.state.setdefault("hybrid_cache", {})
    if not cache_dict:
        # If cache is completely empty, it's a guaranteed miss
        return None
        
    try:
        # Get decision from LLM
        decision_obj = get_llm_decision(query, cache_dict)
        decision = decision_obj.decision.strip().lower()
        
        if decision == "full" and decision_obj.matching_query:
            matched_q = decision_obj.matching_query
            if matched_q in cache_dict:
                cached_res = cache_dict[matched_q]
                
                # Update LRU order: remove and re-add key to make it most recent
                cache_dict.pop(matched_q)
                cache_dict[matched_q] = cached_res
                callback_context.state["hybrid_cache"] = cache_dict
                
                print(f"--- [Cache HIT (Full)] Match found: '{query}' -> '{matched_q}' ---")
                return types.Content(parts=[types.Part(text=cached_res)])
                
        elif decision == "partial" and decision_obj.matching_query and decision_obj.partial_answer:
            matched_q = decision_obj.matching_query
            partial_ans = decision_obj.partial_answer
            
            # Update LRU order for matched query
            if matched_q in cache_dict:
                cached_res = cache_dict[matched_q]
                cache_dict.pop(matched_q)
                cache_dict[matched_q] = cached_res
                callback_context.state["hybrid_cache"] = cache_dict
                
            print(f"--- [Cache HIT (Partial)] Match found: '{query}' -> '{matched_q}' ---")
            
            # Enrich the last user event content with partial answer context
            for event in reversed(callback_context.session.events):
                if event.author == "user" and event.content and event.content.parts:
                    original_text = "".join(p.text for p in event.content.parts if p.text)
                    new_text = f"""[Partial Answer Context from Cache]:
{partial_ans}

[User Query]:
{original_text}

Instructions: Use the provided partial answer context to construct your response, and address the remaining/modified parts of the user query."""
                    event.content = types.Content(parts=[types.Part(text=new_text)])
                    break
                    
    except Exception as e:
        print(f"Error in before_agent_hybrid_cache_callback: {e}")
        
    return None

def after_agent_hybrid_cache_callback(callback_context) -> Optional[types.Content]:
    """
    After Agent Callback: Saves the query-response pair to cache dictionary.
    """
    # Retrieve original query
    original_query = callback_context.state.get("temp:original_query")
    if not original_query or not original_query.strip():
        # Fallback to current user content if original wasn't stored
        if callback_context.user_content and callback_context.user_content.parts:
            original_query = "".join(part.text for part in callback_context.user_content.parts if part.text)
            
    if not original_query or not original_query.strip():
        return None
        
    # Get agent response text
    response_text = ""
    for event in reversed(callback_context.session.events):
        if event.author == callback_context.agent_name and event.content:
            response_text = "".join(part.text for part in event.content.parts if part.text)
            if response_text:
                break
                
    if not response_text.strip():
        return None
        
    try:
        cache_dict = callback_context.state.setdefault("hybrid_cache", {})
        
        # Save query-response pair (update insertion order for LRU)
        if original_query in cache_dict:
            cache_dict.pop(original_query)
        cache_dict[original_query] = response_text
        
        # Enforce maximum cache size of 20 (FIFO/LRU order of dictionary keys)
        if len(cache_dict) > 20:
            first_key = next(iter(cache_dict))
            cache_dict.pop(first_key)
            
        callback_context.state["hybrid_cache"] = cache_dict
        
        # Clean up temporary query state
        callback_context.state.setdefault("temp:original_query", None)
        if "temp:original_query" in callback_context.state:
            del callback_context.state["temp:original_query"]
            
        print(f"--- [Cache MISS/Partial Update] Cached query: '{original_query}' ---")
    except Exception as e:
        print(f"Error in after_agent_hybrid_cache_callback: {e}")
        
    return None
