import asyncio
from core.bots.test_browser import launch_browser

async def test():
    pw, browser, ctx, page = await launch_browser(headless=True)
    await page.goto("https://www.google.com",timeout=35000)
    print("pagina abierta")
    await browser.close()
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(test())