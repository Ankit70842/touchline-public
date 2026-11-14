async page => {
  const errors=[], external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:8000')&&!r.url().startsWith('data:'))external.push(r.url());});
  await page.goto('http://127.0.0.1:8000');
  await page.locator('#detail h3').waitFor();
  if(!(await page.locator('#source-status').innerText()).includes('SYNTHETIC DEMO'))throw new Error('Missing demo banner');
  await page.locator('#search').fill('Demo Player 01');
  await page.locator('#player-list .player').first().click();
  await page.waitForFunction(()=>document.querySelector('#detail h3')?.textContent==='Demo Player 01');
  await page.locator('#model-select').selectOption('stats_only');
  if(!(await page.locator('.model-explanation').innerText()).includes('not a trained model'))throw new Error('Illustration mislabeled');
  await page.locator('#model-select').selectOption('valuation_aware');
  if(!(await page.locator('.model-explanation').innerText()).includes('Previous-value baseline'))throw new Error('Baseline mislabeled');
  await page.locator('#toggle-scenario').click();
  await page.locator('[name=previous_value]').fill('750000');
  await page.getByRole('button',{name:'Calculate scenario'}).click();
  await page.waitForFunction(()=>document.querySelector('#scenario-result')?.textContent.includes('previous value'));
  if(!(await page.locator('#scenario-result strong').innerText()).includes('750'))throw new Error('Scenario mismatch');
  await page.locator('[name=goals]').fill('0');await page.locator('[name=recent_goals]').fill('2');
  await page.getByRole('button',{name:'Calculate scenario'}).click();
  await page.waitForFunction(()=>document.querySelector('#scenario-result')?.textContent.includes('90-day totals'));
  await page.getByRole('button',{name:'Model & data',exact:true}).click();
  if(!(await page.locator('#method-content').innerText()).includes('no production evaluation'))throw new Error('Fake evaluation');
  await page.setViewportSize({width:390,height:844});
  if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw new Error('Mobile overflow');
  if(errors.length||external.length)throw new Error('Browser errors or external dependency');
  return {passed:7,checks:['fictional banner','search/report','model labels','baseline scenario','invalid input','no fake metrics','mobile/errors/offline assets']};
}
