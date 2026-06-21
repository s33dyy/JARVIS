"""
jarvis_youtube.py
-----------------
Module for playing YouTube videos via browser automation.
"""

import urllib.parse
import subprocess
import time

def play_on_youtube(query: str) -> str:
    """
    Search and play a video on YouTube.
    Attempts to use Playwright via jarvis_browser to automatically click the first video.
    Falls back to opening the search results in the default browser.
    """
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    
    try:
        import jarvis_browser
        # If Playwright is available, open the browser and click the first result
        if jarvis_browser._PLAYWRIGHT_AVAILABLE:
            jarvis_browser.open_url(search_url)
            
            _, _, page = jarvis_browser._get_browser()
            
            # Wait for video thumbnails to load
            try:
                # Accept cookies if the popup appears (EU)
                try:
                    page.locator('button:has-text("Accept all"), button:has-text("I agree")').click(timeout=2000)
                except Exception:
                    pass
                    
                # Click the first video thumbnail
                # YouTube uses ytd-video-renderer for search results
                first_video = page.locator('ytd-video-renderer a#video-title').first
                first_video.wait_for(timeout=5000)
                title = first_video.inner_text()
                first_video.click()
                
                return f"Playing '{title}' on YouTube, sir."
            except Exception as e:
                # If clicking fails, just leave it on the search page
                return f"Opened YouTube search for '{query}', sir. Please select a video."
    except ImportError:
        pass
        
    # Fallback to default browser
    try:
        subprocess.run(["open", search_url])
        return f"Opened YouTube search for '{query}' in your default browser, sir."
    except Exception as e:
        return f"Failed to open YouTube: {e}"
