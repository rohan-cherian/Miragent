import { chromium } from 'playwright'
import fs from 'fs'

const OUT = process.argv[2] || 'shots'
fs.mkdirSync(OUT, { recursive: true })

const errors = []
const browser = await chromium.launch({ args: ['--no-sandbox'] })
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await ctx.newPage()
page.on('console', (m) => { if (m.type() === 'error') errors.push(`[console] ${m.text()}`) })
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))

const shot = async (name) => {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false })
  console.log(`  shot ${name}`)
}

const go = async (url, waitText, name) => {
  console.log(`\n=== ${name} :: ${url}`)
  await page.goto(`http://localhost:5173${url}`, { waitUntil: 'domcontentloaded' })
  if (waitText) {
    try { await page.getByText(waitText, { exact: false }).first().waitFor({ timeout: 12000 }) }
    catch (e) { console.log(`  !! did not find "${waitText}"`) }
  }
  await page.waitForTimeout(600)
  await shot(name)
}

// --- S-14 login, pick Manager (the Operations Manager persona) ---
await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded' })
await page.getByText('Motiveminds ITR').first().waitFor({ timeout: 15000 })
await shot('01-login')
await page.getByRole('radio', { name: /Manager/ }).first().click()
await page.getByRole('button', { name: 'Continue' }).click()
await page.getByText('Overview').first().waitFor({ timeout: 15000 })
await page.waitForTimeout(1500)
await shot('02-dashboard-manager')

// drill from a chart segment
const bar = page.locator('button.bar-row').first()
if (await bar.count()) {
  await bar.click()
  await page.waitForTimeout(1200)
  await shot('03-drill-panel')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
}

await go('/intelligence', 'Week 32', '04-digest')
await go('/tickets?status=open', 'Tickets', '05-tickets')
await go('/audit', 'Audit', '06-audit')
await go('/case/HFG-2214', 'Daniel Okafor', '07-case360')
await go('/case/HFG-2214?tab=citations', 'Compiled', '08-citations')
await go('/case/HFG-2214?tab=explainers', 'Classification', '09-explainers')
await go('/case/HFG-2214?tab=assignment', 'Shortlist', '10-assignment')
await go('/queue', 'Approval queue', '11-queue-manager')
await go('/connections', 'Connections', '12-connections')
await go('/knowledge', 'Knowledge', '13-knowledge')
await go('/kitchen-sink', 'Kitchen sink', '14-kitchen-sink')

// --- switch to Analyst and exercise the decision path ---
await page.goto('http://localhost:5173/login?switch=1', { waitUntil: 'domcontentloaded' })
await page.getByRole('radio', { name: /Analyst/ }).first().click()
await page.getByRole('button', { name: 'Continue' }).click()
await page.getByText('Approval queue').first().waitFor({ timeout: 15000 })
await page.waitForTimeout(1800)
await shot('15-queue-analyst')

// approve the medium-band merge item's sibling: pick HFG-2402 (write-failed state)
await page.goto('http://localhost:5173/queue?item=HFG-2402', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(1800)
await shot('16-write-failed')

// low-confidence item: approve must open the confirm modal
await page.goto('http://localhost:5173/queue?item=HFG-2308', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(1800)
const approve = page.getByRole('button', { name: /^Approve/ }).first()
if (await approve.count()) {
  await approve.click()
  await page.waitForTimeout(700)
  await shot('17-low-confidence-friction')
  await page.keyboard.press('Escape')
}

// demo role
await page.goto('http://localhost:5173/login?switch=1', { waitUntil: 'domcontentloaded' })
await page.getByRole('radio', { name: /Demo/ }).first().click()
await page.getByRole('button', { name: 'Continue' }).click()
await page.waitForTimeout(1800)
await shot('18-demo-d1')

// scripted failure hook
await go('/overview?error=1', 'unreachable', '19-error-state')
await go('/queue?empty=1', 'No items', '20-empty-state')

console.log('\n=== console errors ===')
if (errors.length === 0) console.log('  none')
else errors.forEach((e) => console.log('  ' + e))

await browser.close()
