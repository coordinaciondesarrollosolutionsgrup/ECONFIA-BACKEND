from playwright.async_api import async_playwright

async def launch_browser(headless=True):
    playwright = await async_playwright().start()

    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    context = await browser.new_context()
    page = await context.new_page()

    return playwright, browser, context, page
