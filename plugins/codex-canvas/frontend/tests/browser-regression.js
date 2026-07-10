async (page) => {
  const assert = (value, message) => {
    if (!value) throw new Error(message);
  };
  const count = (selector) => page.locator(selector).count();
  const sleep = (milliseconds = 500) => page.waitForTimeout(milliseconds);
  const waitFor = async (check, message, timeout = 6000) => {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      if (await check()) return;
      await sleep(120);
    }
    throw new Error(message);
  };
  const drag = async (start, end) => {
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move((start.x + end.x) / 2, (start.y + end.y) / 2, { steps: 5 });
    await page.mouse.move(end.x, end.y, { steps: 5 });
    await page.mouse.up();
  };
  const center = (box) => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
  const transform = (selector) => page.locator(selector).evaluate((element) => element.style.transform);
  const position = async (selector) => {
    const value = await transform(selector);
    const match = value.match(/translate\(([-\d.]+)px,\s*([-\d.]+)px\)/);
    assert(match, `missing transform for ${selector}: ${value}`);
    return { x: Number(match[1]), y: Number(match[2]) };
  };
  const almostEqual = (left, right, tolerance = 1.5) => Math.abs(left - right) <= tolerance;

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.waitForSelector('.vue-flow__node-checkpoint');
  await waitFor(async () => (await count('.vue-flow__node-checkpoint')) === 6, 'checkpoint nodes did not render');
  assert((await count('.formal-edge')) === 5, 'initial formal edge count mismatch');
  assert((await count('.vue-flow__node-discussion')) === 1, 'discussion node missing');
  assert((await count('.discussion-edge')) === 1, 'automatic discussion edge missing');
  assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)), 'desktop body overflow');

  const discussionBeforeSelection = await transform('.vue-flow__node-discussion');
  const discussionEdgeBeforeSelection = await page.locator('[data-id^="discussion:"]').getAttribute('data-id');
  await page.getByRole('heading', { name: 'UI 节点 1', exact: true }).click();
  await sleep(250);
  assert((await page.locator('.inspector-scroll > h2').textContent()) === 'UI 节点 1', 'node click did not open details');
  assert((await transform('.vue-flow__node-discussion')) === discussionBeforeSelection, 'node selection moved discussion node');
  assert((await page.locator('[data-id^="discussion:"]').getAttribute('data-id')) === discussionEdgeBeforeSelection, 'node selection changed discussion source');
  assert((await count('.inspector-panel script')) === 0, 'markdown sanitizer left a script element');
  assert((await count('.inspector-panel [onclick]')) === 0, 'markdown sanitizer left an onclick handler');
  const detailLink = page.locator('.markdown-content a').first();
  assert((await detailLink.getAttribute('target')) === '_blank', 'markdown link does not open in a new tab');
  assert((await detailLink.getAttribute('rel')) === 'noopener noreferrer', 'markdown link is missing safe rel attributes');

  const searchInput = page.getByRole('searchbox', { name: '搜索检查点' });
  await searchInput.fill('UI 节点 3');
  await page.locator('.search-results button').filter({ hasText: 'UI 节点 3' }).click();
  await sleep(250);
  assert((await searchInput.inputValue()) === '', 'search did not clear after result selection');
  assert((await page.locator('.inspector-scroll > h2').textContent()) === 'UI 节点 3', 'search result did not focus node');

  const draft = 'BROWSER-DRAFT-KEEP\nrefresh and reload must preserve this text';
  await page.getByRole('textbox', { name: '组装后的上下文' }).fill(draft);
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await sleep(650);
  assert((await page.getByRole('textbox', { name: '组装后的上下文' }).inputValue()) === draft, 'refresh cleared composer draft');
  await page.reload();
  await page.waitForSelector('.vue-flow__node-checkpoint');
  assert((await page.getByRole('textbox', { name: '组装后的上下文' }).inputValue()) === draft, 'reload cleared composer draft');
  await page.getByRole('button', { name: '重新生成', exact: true }).click();

  await page.getByRole('button', { name: '显示全部节点', exact: true }).click();
  await sleep(550);
  const box4 = await page.locator('[data-id="ui_4"]').boundingBox();
  const box5 = await page.locator('[data-id="ui_5"]').boundingBox();
  const stage = await page.locator('.canvas-stage').boundingBox();
  assert(box4 && box5 && stage, 'missing lasso geometry');
  const union = {
    left: Math.min(box4.x, box5.x),
    top: Math.min(box4.y, box5.y),
    right: Math.max(box4.x + box4.width, box5.x + box5.width),
    bottom: Math.max(box4.y + box4.height, box5.y + box5.height),
  };
  const candidates = [];
  for (const xMargin of [8, 16, 24, 32, 40, 52, 64, 76]) {
    for (const yMargin of [8, 16, 24, 32, 40, 52, 64, 76]) {
      candidates.push(
        {
          start: { x: union.right + xMargin, y: union.bottom + yMargin },
          end: { x: union.left - 8, y: union.top - 8 },
        },
        {
          start: { x: union.right + xMargin, y: union.top - yMargin },
          end: { x: union.left - 8, y: union.bottom + 8 },
        },
        {
          start: { x: union.left - xMargin, y: union.bottom + yMargin },
          end: { x: union.right + 8, y: union.top - 8 },
        },
        {
          start: { x: union.left - xMargin, y: union.top - yMargin },
          end: { x: union.right + 8, y: union.bottom + 8 },
        },
      );
    }
  }
  const validCandidates = candidates.filter(({ start, end }) =>
    [start, end].every((point) =>
      point.x > stage.x + 2 &&
      point.y > stage.y + 2 &&
      point.x < stage.x + stage.width - 2 &&
      point.y < stage.y + stage.height - 2,
    ),
  );
  let lasso = null;
  for (const candidate of validCandidates) {
    const hitsPane = await page.evaluate(
      (point) => document.elementFromPoint(point.x, point.y)?.classList.contains('vue-flow__pane') || false,
      candidate.start,
    );
    if (hitsPane) {
      lasso = candidate;
      break;
    }
  }
  if (!lasso) {
    const diagnostics = await page.evaluate(
      ({ candidates: values, stage: stageBox, union: unionBox }) => ({
        stage: stageBox,
        union: unionBox,
        candidates: values.map((candidate) => ({
          ...candidate,
          hit: (() => {
            const element = document.elementFromPoint(candidate.start.x, candidate.start.y);
            return element ? { tag: element.tagName, className: String(element.className) } : null;
          })(),
        })),
      }),
      { candidates: validCandidates, stage, union },
    );
    throw new Error(`could not find an empty lasso start point: ${JSON.stringify(diagnostics)}`);
  }
  await drag(lasso.start, lasso.end);
  await waitFor(async () => (await count('.vue-flow__node-checkpoint.selected')) === 2, 'lasso did not select two nodes');
  const selectedIds = await page.locator('.vue-flow__node-checkpoint.selected').evaluateAll((elements) => elements.map((element) => element.dataset.id).sort());
  assert(JSON.stringify(selectedIds) === JSON.stringify(['ui_4', 'ui_5']), `lasso selected wrong nodes: ${selectedIds.join(',')}`);
  assert((await count('.vue-flow__node-discussion.selected')) === 0, 'lasso selected discussion node');

  const groupBefore4 = await position('[data-id="ui_4"]');
  const groupBefore5 = await position('[data-id="ui_5"]');
  const groupDiscussionBefore = await transform('.vue-flow__node-discussion');
  const groupLead = await page.locator('[data-id="ui_4"]').boundingBox();
  assert(groupLead, 'missing group drag lead');
  const groupStart = { x: groupLead.x + groupLead.width / 2, y: groupLead.y + 34 };
  await drag(groupStart, { x: groupStart.x + 62, y: groupStart.y + 26 });
  await sleep(700);
  const groupAfter4 = await position('[data-id="ui_4"]');
  const groupAfter5 = await position('[data-id="ui_5"]');
  assert(almostEqual(groupAfter4.x - groupBefore4.x, groupAfter5.x - groupBefore5.x), 'group drag x deltas differ');
  assert(almostEqual(groupAfter4.y - groupBefore4.y, groupAfter5.y - groupBefore5.y), 'group drag y deltas differ');
  assert((await transform('.vue-flow__node-discussion')) === groupDiscussionBefore, 'group drag moved discussion node');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await sleep(700);
  const groupUndo4 = await position('[data-id="ui_4"]');
  assert(almostEqual(groupUndo4.x, groupBefore4.x) && almostEqual(groupUndo4.y, groupBefore4.y), 'group drag undo failed');

  const discussionBox = await page.locator('.vue-flow__node-discussion').boundingBox();
  assert(discussionBox, 'missing discussion drag geometry');
  const formalBeforeDiscussionDrag = await transform('[data-id="ui_4"]');
  const discussionBeforeDrag = await transform('.vue-flow__node-discussion');
  const discussionStart = { x: discussionBox.x + discussionBox.width / 2, y: discussionBox.y + 20 };
  await drag(discussionStart, { x: discussionStart.x + 68, y: discussionStart.y - 16 });
  await sleep(700);
  assert((await transform('.vue-flow__node-discussion')) !== discussionBeforeDrag, 'discussion drag did not move');
  assert((await transform('[data-id="ui_4"]')) === formalBeforeDiscussionDrag, 'discussion drag moved a formal node');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await sleep(700);
  assert((await transform('.vue-flow__node-discussion')) === discussionBeforeDrag, 'discussion drag undo failed');

  const sourceHandle = await page.locator('[data-id="ui_1"] .checkpoint-handle-out').boundingBox();
  const targetHandle = await page.locator('[data-id="ui_6"] .checkpoint-handle-in').boundingBox();
  assert(sourceHandle && targetHandle, 'missing connection handles');
  await drag(center(sourceHandle), center(targetHandle));
  await waitFor(async () => (await count('.formal-edge')) === 6, 'new formal edge was not created');
  const extraEdge = page.locator('[aria-label="Edge from ui_1 to ui_6"]');
  const extraEdgeId = await extraEdge.getAttribute('data-id');
  assert(extraEdgeId, 'new edge id missing');
  await extraEdge.evaluate((element) => element.dispatchEvent(new MouseEvent('click', { bubbles: true })));
  await sleep(200);
  assert(await page.getByRole('button', { name: '删除选中关系', exact: true }).isVisible(), 'selected-edge delete button missing');
  await page.getByRole('button', { name: '删除选中关系', exact: true }).click();
  await waitFor(async () => (await count('.formal-edge')) === 5, 'delete button did not remove formal edge');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await waitFor(async () => (await count('.formal-edge')) === 6, 'formal edge undo failed');

  const restoredEdge = page.locator(`[data-id="${extraEdgeId}"]`);
  await restoredEdge.evaluate((element) => element.dispatchEvent(new MouseEvent('click', { bubbles: true })));
  const updater = await restoredEdge.locator('.vue-flow__edgeupdater-source').boundingBox();
  const reconnectTarget = await page.locator('[data-id="ui_2"] .checkpoint-handle-out').boundingBox();
  assert(updater && reconnectTarget, 'missing edge reconnect geometry');
  await drag(center(updater), center(reconnectTarget));
  await waitFor(
    async () => (await restoredEdge.getAttribute('aria-label')) === 'Edge from ui_2 to ui_6',
    'edge source reconnect failed',
  );
  assert((await count('.formal-edge')) === 6, 'edge reconnect changed edge count');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await waitFor(
    async () => (await restoredEdge.getAttribute('aria-label')) === 'Edge from ui_1 to ui_6',
    'edge reconnect undo failed',
  );

  const discussionPositionBeforeConnect = await transform('.vue-flow__node-discussion');
  const discussionTarget = await page.locator('.vue-flow__node-discussion .checkpoint-handle-in').boundingBox();
  const source2 = await page.locator('[data-id="ui_2"] .checkpoint-handle-out').boundingBox();
  assert(discussionTarget && source2, 'missing first discussion connection geometry');
  await drag(center(source2), center(discussionTarget));
  await waitFor(async () => (await count('[data-id="discussion:ui_2"]')) === 1, 'first discussion source failed');
  assert((await page.locator('[data-id="discussion:ui_2"]').getAttribute('aria-label')) === 'Edge from ui_2 to __discussion__', 'wrong first discussion source');
  assert((await transform('.vue-flow__node-discussion')) === discussionPositionBeforeConnect, 'manual discussion connection moved node');
  const source3 = await page.locator('[data-id="ui_3"] .checkpoint-handle-out').boundingBox();
  const discussionTarget2 = await page.locator('.vue-flow__node-discussion .checkpoint-handle-in').boundingBox();
  assert(source3 && discussionTarget2, 'missing second discussion connection geometry');
  await drag(center(source3), center(discussionTarget2));
  await waitFor(async () => (await count('.discussion-edge')) === 2, 'second discussion source failed');
  assert((await transform('.vue-flow__node-discussion')) === discussionPositionBeforeConnect, 'second discussion connection moved node');

  const discussionEdge2 = page.locator('[data-id="discussion:ui_2"]');
  await discussionEdge2.evaluate((element) => element.dispatchEvent(new MouseEvent('click', { bubbles: true })));
  await page.getByRole('button', { name: '删除选中关系', exact: true }).click();
  await waitFor(async () => (await count('.discussion-edge')) === 1, 'discussion source delete failed');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await waitFor(async () => (await count('.discussion-edge')) === 2, 'discussion source undo failed');

  await page.getByRole('button', { name: '恢复自动跟随', exact: true }).click();
  await waitFor(async () => (await count('[data-id="discussion:ui_6"]')) === 1, 'discussion auto-follow restore failed');
  assert((await count('.discussion-edge')) === 1, 'auto-follow restore kept manual sources');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await waitFor(async () => (await count('.discussion-edge')) === 2, 'discussion auto-follow undo failed');

  const customState = {
    formal: await count('.formal-edge'),
    discussion: await count('.discussion-edge'),
    node: await transform('[data-id="ui_4"]'),
  };
  await page.getByRole('button', { name: '还原画布', exact: true }).click();
  await waitFor(async () => (await count('.formal-edge')) === 5, 'reset did not restore mainline edges');
  assert((await count('.discussion-edge')) === 1, 'reset did not restore automatic discussion source');
  assert((await count('.vue-flow__node-checkpoint')) === 6, 'reset changed checkpoint count');
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await waitFor(async () => (await count('.formal-edge')) === customState.formal, 'reset undo did not restore formal edges');
  assert((await count('.discussion-edge')) === customState.discussion, 'reset undo did not restore discussion sources');
  assert((await transform('[data-id="ui_4"]')) === customState.node, 'reset undo did not restore layout');

  await page.setViewportSize({ width: 390, height: 844 });
  await sleep(750);
  const mobile = await page.evaluate(() => {
    const stageRect = document.querySelector('.canvas-stage').getBoundingClientRect();
    const visibleNodes = [...document.querySelectorAll('.vue-flow__node-checkpoint')].filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.right > stageRect.left && rect.left < stageRect.right && rect.bottom > stageRect.top && rect.top < stageRect.bottom;
    }).length;
    const discussionRect = document.querySelector('.vue-flow__node-discussion').getBoundingClientRect();
    return {
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      visibleNodes,
      discussionVisible:
        discussionRect.right > stageRect.left &&
        discussionRect.left < stageRect.right &&
        discussionRect.bottom > stageRect.top &&
        discussionRect.top < stageRect.bottom,
      textOverflow: [...document.querySelectorAll('.checkpoint-node h3,.checkpoint-node p,.node-tag')].some(
        (element) => element.scrollWidth > element.clientWidth + 1,
      ),
    };
  });
  assert(!mobile.overflow, 'mobile body overflow');
  assert(mobile.visibleNodes > 0 && mobile.discussionVisible, 'viewport breakpoint did not refit canvas');
  assert(!mobile.textOverflow, 'mobile node text overflow');
  await page.getByRole('heading', { name: 'UI 节点 6', exact: true }).click();
  await sleep(250);
  const inspector = await page.locator('.inspector-panel').boundingBox();
  assert(inspector && inspector.x >= 0 && inspector.x + inspector.width <= 390.5, 'mobile inspector is outside viewport');
  assert(await page.getByRole('button', { name: '关闭详情', exact: true }).isVisible(), 'mobile inspector close button missing');
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();

  await page.setViewportSize({ width: 1024, height: 768 });
  await sleep(650);
  assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)), 'tablet body overflow');

  return {
    ok: true,
    nodes: await count('.vue-flow__node-checkpoint'),
    formalEdges: await count('.formal-edge'),
    discussionEdges: await count('.discussion-edge'),
    mobileVisibleNodes: mobile.visibleNodes,
  };
}
