import re

def parse_msg(q):
    # 1. "send a [msg] message from/via/on [platform] to [contact]"
    # 2. "message [contact] saying [msg]"
    # 3. "whatsapp [contact] saying [msg]"
    # 4. "text [contact] [msg]"
    # 5. "open whatsapp and message [contact]"
    
    q_clean = re.sub(r'[\.\!\?]+$', '', q.strip()).strip()
    
    # 1. send ... to ...
    m = re.search(r"\bsend\b\s+(?:a\s+)?(.*?)\s*(?:message|text|whatsapp)?\s*(?:from|via|on)?\s*(?:whatsapp|imessage)?\s*to\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE)
    if m:
        msg = m.group(1).strip()
        if msg.lower() == "hello": msg = "Hello"
        return m.group(2).strip(), msg
        
    # 2. open whatsapp and message ...
    m = re.search(r"\bopen whatsapp and message\b\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE)
    if m:
        return m.group(1).strip(), "Hello"
        
    # 3. message/text/whatsapp ... saying ...
    m = re.search(r"\b(?:message|text|whatsapp|imessage)\b\s+([A-Za-z0-9_ ]+?)\s+(?:saying|that says|to say|and say)\s+(.+)$", q_clean, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # 4. send whatsapp to ...
    m = re.search(r"\bsend\s+(?:a\s+)?(?:whatsapp|text|message|imessage)\s+to\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE)
    if m:
        return m.group(1).strip(), "Hello"

    # 5. whatsapp/message/text ...
    m = re.search(r"\b(?:whatsapp|message|text|imessage)\b\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE)
    if m:
        return m.group(1).strip(), "Hello"
        
    return None, None

qs = [
    "send a hello message from whatsapp to vivoor.",
    "open whatsapp and message before.",
    "message john saying hello.",
    "text john hello.",
    "send whatsapp to john.",
    "send a message to john",
    "whatsapp john"
]

for q in qs:
    contact, msg = parse_msg(q)
    print(f"[{q}] -> Contact: '{contact}', Msg: '{msg}'")

