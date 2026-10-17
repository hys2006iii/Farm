/* ============================================================
 * ai.js — AI 助手对话（气泡全部走 textContent，无 innerHTML 拼接）
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;
    var sending = false;

    /** 追加一个聊天气泡（纯文本，天然免疫 XSS） */
    function appendBubble(cls, text) {
        var history = QH.$('chatHistory');
        if (!history) return null;
        var div = document.createElement('div');
        div.className = 'chat-bubble ' + cls;
        div.textContent = text;
        history.appendChild(div);
        history.scrollTop = history.scrollHeight;
        return div;
    }

    /** 发送问题给 AI 助手 */
    async function sendChat() {
        if (sending) return;
        var inputEl = QH.$('chatInput');
        if (!inputEl) return;
        var msg = inputEl.value.trim();
        if (!msg) return;

        sending = true;
        appendBubble('chat-user', msg);
        inputEl.value = '';

        var aiDiv = appendBubble('chat-ai', '正在处理...');

        try {
            var res = await fetch('/api/ai_chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg })
            });
            var data = await res.json();
            if (data && data.choices && data.choices.length > 0) {
                aiDiv.textContent = data.choices[0].message.content;
            } else {
                aiDiv.textContent = '数据返回异常';
            }
        } catch (e) {
            aiDiv.textContent = '连接网络失败';
        }
        var history = QH.$('chatHistory');
        if (history) history.scrollTop = history.scrollHeight;
        sending = false;
    }

    root.QH_AI = { sendChat: sendChat, appendBubble: appendBubble };
    root.sendChat = sendChat;
})(typeof globalThis !== 'undefined' ? globalThis : this);
