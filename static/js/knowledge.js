/**
 * knowledge.js —— 「知识库」页面的纯前端交互
 *
 * 职责（全部在前端完成，不请求任何接口）：
 *   1. 章节目录高亮：滚动时按标题位置切换当前章节；
 *   2. 阅读进度条：随滚动更新顶栏下方细线宽度；
 *   3. 回到顶部：滚动超过一屏后出现，点击平滑回顶；
 *   4. 移动端目录开关：≤900px 时目录折叠，按钮展开 / Esc 收起；
 *   5. 章节搜索：按标题过滤左侧目录，同时过滤问答条目。
 *
 * 工程约定（见 AGENTS.md）：
 *   - 统一用 document.querySelector / querySelectorAll 取节点，不用全局 id 查找；
 *   - 写入页面文本一律用 textContent，不做 HTML 字符串拼接；
 *   - 所有事件监听器登记在 listeners 中，window.KnowledgePage.destroy() 可整体清理；
 *   - 不引入定时器轮询，滚动只在一个 requestAnimationFrame 里处理。
 */
(function (root, doc) {
    'use strict';

    /** 章节目录吸顶后的判定偏移，与 knowledge.css 的 scroll-padding-top 保持接近 */
    var SCROLL_OFFSET = 96;
    /** 移动端断点，与 knowledge.css 中目录折叠的媒体查询一致 */
    var MOBILE_QUERY = '(max-width: 900px)';

    var listeners = [];
    var frame = 0;
    var started = false;
    var refs = {};

    /**
     * 登记事件监听器，destroy() 时按同一组参数移除。
     *
     * @param {EventTarget|null} target 事件目标
     * @param {string} type 事件名
     * @param {Function} handler 处理函数
     * @param {Object|boolean} [options] 监听选项
     */
    function on(target, type, handler, options) {
        if (!target || !target.addEventListener) {
            return;
        }
        target.addEventListener(type, handler, options);
        listeners.push({ target: target, type: type, handler: handler, options: options });
    }

    /**
     * 读取节点可见文本并归一化（压缩空白、转小写），供搜索匹配使用。
     *
     * @param {Element|null} el 目标节点
     * @returns {string} 归一化后的文本
     */
    function textOf(el) {
        if (!el) {
            return '';
        }
        var raw = el.textContent || '';
        return raw.replace(/\s+/g, ' ').trim().toLowerCase();
    }

    /**
     * 判断节点的文本是否包含全部关键词（多关键词之间是「与」关系）。
     *
     * @param {Element|null} el 目标节点
     * @param {string[]} tokens 已小写的关键词数组
     * @returns {boolean} 是否命中
     */
    function matches(el, tokens) {
        var text = textOf(el);
        if (!text) {
            return false;
        }
        for (var i = 0; i < tokens.length; i += 1) {
            if (text.indexOf(tokens[i]) === -1) {
                return false;
            }
        }
        return true;
    }

    /**
     * 把类数组对象转成真数组，便于使用 forEach。
     *
     * @param {NodeList|Array} list 类数组
     * @returns {Element[]} 数组
     */
    function toArray(list) {
        return Array.prototype.slice.call(list || []);
    }

    /**
     * 取当前滚动距离（兼容旧版浏览器）。
     *
     * @returns {number} 纵向滚动像素
     */
    function scrollTop() {
        return root.pageYOffset || doc.documentElement.scrollTop || doc.body.scrollTop || 0;
    }

    /**
     * 主题是否开启了「减弱动效」，开启时不做平滑滚动。
     *
     * @returns {boolean} 是否减弱动效
     */
    function reducedMotion() {
        return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    /**
     * 目录高亮切换：给当前章节对应的目录项打上 is-active。
     *
     * @param {Object} activeIds 需要高亮的锚点 id 集合（键为 id）
     */
    function markActive(activeIds) {
        refs.links.forEach(function (link) {
            var isActive = !!activeIds[link.getAttribute('data-toc-link')];
            link.classList.toggle('is-active', isActive);
            if (isActive) {
                link.setAttribute('aria-current', 'true');
            } else {
                link.removeAttribute('aria-current');
            }
        });
    }

    /**
     * 单帧内更新进度条、回到顶部按钮与目录高亮（滚动只触发这一处）。
     */
    function updateScrollUi() {
        frame = 0;

        var top = scrollTop();
        var scrollHeight = doc.documentElement.scrollHeight || 0;
        var viewport = root.innerHeight || doc.documentElement.clientHeight || 0;
        var total = scrollHeight - viewport;

        if (refs.progress) {
            var pct = total > 0 ? (top / total) * 100 : 0;
            if (pct < 0) { pct = 0; }
            if (pct > 100) { pct = 100; }
            refs.progress.style.width = pct.toFixed(2) + '%';
        }

        if (refs.topBtn) {
            refs.topBtn.classList.toggle('is-visible', top > 420);
        }

        /* 未进入正文时默认高亮第一章；小节高亮时同步点亮所属章 */
        var currentId = refs.headings.length > 0 ? refs.headings[0].id : '';
        refs.headings.forEach(function (heading) {
            var rect = heading.getBoundingClientRect();
            if (rect.top - SCROLL_OFFSET <= 0) {
                currentId = heading.id;
            }
        });

        var activeIds = {};
        if (currentId) {
            activeIds[currentId] = true;
            var parent = /^(ch-\d+)-\d+$/.exec(currentId);
            if (parent) {
                activeIds[parent[1]] = true;
            }
        }
        markActive(activeIds);
    }

    /**
     * 请求下一帧刷新；同一帧内的多次滚动事件会被合并。
     */
    function scheduleScrollUi() {
        if (frame) {
            return;
        }
        if (root.requestAnimationFrame) {
            frame = root.requestAnimationFrame(updateScrollUi);
        } else {
            updateScrollUi();
        }
    }

    /**
     * 展开 / 收起移动端目录，并同步按钮的 aria-expanded。
     *
     * @param {boolean} open 是否展开
     */
    function setTocOpen(open) {
        if (!refs.toc || !refs.tocToggle) {
            return;
        }
        refs.toc.classList.toggle('is-open', open);
        refs.tocToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    /**
     * 目录当前是否处于展开状态。
     *
     * @returns {boolean} 是否展开
     */
    function isTocOpen() {
        return !!(refs.toc && refs.toc.classList.contains('is-open'));
    }

    /**
     * 章节搜索的核心逻辑：按关键词过滤目录项与问答条目，并在提示行给出结果数。
     *
     * @param {string} rawQuery 搜索框原始输入
     */
    function applyFilter(rawQuery) {
        var tokens = (rawQuery || '').toLowerCase().split(/\s+/).filter(Boolean);
        var tocHits = 0;
        var qaHits = 0;

        refs.groups.forEach(function (group) {
            var titleLink = group.querySelector('.kb-toc-link--ch');
            var titleHit = tokens.length > 0 && matches(titleLink, tokens);
            var subLinks = toArray(group.querySelectorAll('.kb-toc-sub [data-toc-link]'));
            var shown = 0;

            subLinks.forEach(function (link) {
                var hit = tokens.length === 0 || titleHit || matches(link, tokens);
                link.parentElement.classList.toggle('is-hidden', !hit);
                if (hit) {
                    shown += 1;
                }
            });

            var groupVisible = tokens.length === 0 || titleHit || shown > 0;
            group.classList.toggle('is-hidden', !groupVisible);
            if (tokens.length > 0) {
                tocHits += shown;
                if (titleHit) {
                    tocHits += 1;
                }
            }
        });

        refs.qas.forEach(function (item) {
            var hit = tokens.length === 0 || matches(item, tokens);
            item.classList.toggle('is-hidden', !hit);
            if (hit && tokens.length > 0) {
                qaHits += 1;
            }
        });

        if (!refs.hint) {
            return;
        }
        if (tokens.length === 0) {
            refs.hint.textContent = '按标题筛选，清空即恢复全部。';
            refs.hint.classList.remove('is-empty');
            return;
        }
        if (tocHits === 0 && qaHits === 0) {
            refs.hint.textContent = '没有匹配的章节，换个词试试。';
            refs.hint.classList.add('is-empty');
            return;
        }
        refs.hint.textContent = '匹配 ' + tocHits + ' 个章节、' + qaHits + ' 条问答。';
        refs.hint.classList.remove('is-empty');
    }

    /**
     * 绑定全部交互，只在首次调用时生效。
     */
    function start() {
        if (started) {
            return;
        }
        started = true;

        refs = {
            toc: doc.querySelector('#kbToc'),
            tocToggle: doc.querySelector('#kbTocToggle'),
            search: doc.querySelector('#kbSearch'),
            hint: doc.querySelector('#kbSearchHint'),
            topBtn: doc.querySelector('#kbTop'),
            progress: doc.querySelector('#kbProgressBar'),
            headings: toArray(doc.querySelectorAll('[data-toc-target]')),
            links: toArray(doc.querySelectorAll('[data-toc-link]')),
            groups: toArray(doc.querySelectorAll('[data-kb-group]')),
            qas: toArray(doc.querySelectorAll('[data-kb-qa]'))
        };

        /* 滚动：目录高亮 + 进度条 + 回到顶部显隐，统一在一帧内完成 */
        on(root, 'scroll', scheduleScrollUi, { passive: true });

        /* 移动端目录开关 */
        on(refs.tocToggle, 'click', function () {
            setTocOpen(!isTocOpen());
        });

        /* 点击目录锚点后，移动端自动收起目录，避免挡住正文 */
        var mobileQuery = root.matchMedia ? root.matchMedia(MOBILE_QUERY) : null;
        on(refs.toc, 'click', function (event) {
            var target = event.target;
            var anchor = target && target.closest ? target.closest('a[href^="#"]') : null;
            if (anchor && mobileQuery && mobileQuery.matches) {
                setTocOpen(false);
            }
        });

        /* Esc：优先清空搜索，其次收起移动端目录 */
        on(doc, 'keydown', function (event) {
            if (event.key !== 'Escape' && event.key !== 'Esc') {
                return;
            }
            if (refs.search && refs.search.value) {
                refs.search.value = '';
                applyFilter('');
                return;
            }
            if (isTocOpen()) {
                setTocOpen(false);
                if (refs.tocToggle) {
                    refs.tocToggle.focus();
                }
            }
        });

        /* 章节搜索：输入即过滤 */
        on(refs.search, 'input', function () {
            applyFilter(refs.search.value);
        });

        /* 回到顶部 */
        on(refs.topBtn, 'click', function () {
            var behavior = reducedMotion() ? 'auto' : 'smooth';
            if (root.scrollTo) {
                root.scrollTo({ top: 0, behavior: behavior });
            } else {
                root.scrollTo(0, 0);
            }
        });

        /* 视口跨过断点时收起移动端目录，避免宽屏残留展开态 */
        if (mobileQuery) {
            var onBreakpoint = function (event) {
                if (!event.matches) {
                    setTocOpen(false);
                }
            };
            if (mobileQuery.addEventListener) {
                on(mobileQuery, 'change', onBreakpoint);
            } else if (mobileQuery.addListener) {
                mobileQuery.addListener(onBreakpoint);
                listeners.push({
                    target: mobileQuery,
                    type: 'change',
                    handler: onBreakpoint,
                    legacy: true
                });
            }
        }

        /* 首屏：先按当前滚动位置刷新一次，再处理带 #hash 的直达 */
        updateScrollUi();
    }

    /**
     * 移除全部监听器与待执行的动画帧，供页面卸载或测试清理调用。
     */
    function destroy() {
        if (frame && root.cancelAnimationFrame) {
            root.cancelAnimationFrame(frame);
        }
        frame = 0;
        listeners.forEach(function (item) {
            if (item.legacy && item.target.removeListener) {
                item.target.removeListener(item.handler);
            } else if (item.target.removeEventListener) {
                item.target.removeEventListener(item.type, item.handler, item.options);
            }
        });
        listeners = [];
        started = false;
        refs = {};
    }

    if (doc.readyState === 'loading') {
        on(doc, 'DOMContentLoaded', start);
    } else {
        start();
    }

    /* 对外只暴露清理与手动刷新，便于调试和自动化测试 */
    root.KnowledgePage = {
        destroy: destroy,
        refresh: updateScrollUi
    };
})(window, document);
