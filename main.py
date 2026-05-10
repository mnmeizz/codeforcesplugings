# -*- coding: utf-8 -*-
import random
import aiohttp
import datetime
import re
from bs4 import BeautifulSoup
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger


@register("astrbot_plugin_cf_daily", "YourName", "Codeforces 每日一题插件", "2.1.0")
class CFDailyPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.daily_limit = config.get("daily_limit", 1) if config else 1
        self.admin_id = config.get("admin_id", None) if config else None

    # ==================== 数据存储 ====================
    def _get_user_key(self, user_id: str) -> str:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        return f"cf_daily_{user_id}_{today_str}"

    async def _get_user_usage(self, user_id: str) -> int:
        key = self._get_user_key(user_id)
        val = await self.get_kv_data(key, 0)
        return int(val) if val else 0

    async def _increment_user_usage(self, user_id: str):
        key = self._get_user_key(user_id)
        current = await self._get_user_usage(user_id)
        await self.put_kv_data(key, str(current + 1))

    async def _check_quota(self, user_id: str) -> tuple:
        used = await self._get_user_usage(user_id)
        remaining = self.daily_limit - used
        return remaining > 0, remaining

    # ==================== Codeforces API ====================
    async def fetch_problemset(self):
        url = "https://codeforces.com/api/problemset.problems"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if data.get("status") == "OK":
                        return data["result"]["problems"]
                    else:
                        logger.error(f"Codeforces API error: {data.get('comment')}")
                        return None
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None

    async def fetch_problem_statement(self, contest_id: int, index: str):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
        mirror_url = f"https://mirror.codeforces.com/problemset/problem/{contest_id}/{index}"

        async with aiohttp.ClientSession(headers=headers) as session:
            html = None
            for try_url in (url, mirror_url):
                try:
                    async with session.get(try_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            break
                except Exception:
                    continue

            if html is None:
                logger.error(f"无法获取题目页面 {contest_id}{index}")
                return None

        soup = BeautifulSoup(html, 'html.parser')

        title_tag = soup.find('div', class_='title')
        title = title_tag.text.strip() if title_tag else f"{contest_id}{index}"

        time_limit = "N/A"
        memory_limit = "N/A"
        time_limit_tag = soup.find('div', class_='time-limit')
        if time_limit_tag:
            time_limit = time_limit_tag.text.replace('time limit per test', '').strip()
        memory_limit_tag = soup.find('div', class_='memory-limit')
        if memory_limit_tag:
            memory_limit = memory_limit_tag.text.replace('memory limit per test', '').strip()

        problem_statement = soup.find('div', class_='problem-statement')
        if not problem_statement:
            logger.error("未找到题目内容区域")
            return None

        description_html = ""
        input_spec_html = ""
        output_spec_html = ""
        note_html = ""

        desc_div = None
        for div in problem_statement.find_all('div', recursive=False):
            if 'header' in div.get('class', []):
                continue
            if 'input-specification' in div.get('class', []):
                input_spec_html = str(div)
            elif 'output-specification' in div.get('class', []):
                output_spec_html = str(div)
            elif 'note' in div.get('class', []):
                note_html = str(div)
            elif 'sample-tests' not in div.get('class', []) and desc_div is None:
                desc_div = div

        if desc_div:
            description_html = str(desc_div)

        sample_tests = []
        sample_blocks = problem_statement.find_all('div', class_='sample-test')
        if not sample_blocks:
            sample_inputs = problem_statement.find_all('div', class_='input')
            sample_outputs = problem_statement.find_all('div', class_='output')
            for inp_div, out_div in zip(sample_inputs, sample_outputs):
                inp_pre = inp_div.find('pre')
                out_pre = out_div.find('pre')
                if inp_pre and out_pre:
                    sample_tests.append({
                        "input": inp_pre.get_text('\n').strip(),
                        "output": out_pre.get_text('\n').strip()
                    })
        else:
            for block in sample_blocks:
                inp_div = block.find('div', class_='input')
                out_div = block.find('div', class_='output')
                if inp_div and out_div:
                    inp_pre = inp_div.find('pre')
                    out_pre = out_div.find('pre')
                    if inp_pre and out_pre:
                        sample_tests.append({
                            "input": inp_pre.get_text('\n').strip(),
                            "output": out_pre.get_text('\n').strip()
                        })

        return {
            "title": title,
            "time_limit": time_limit,
            "memory_limit": memory_limit,
            "description": description_html,
            "input_spec": input_spec_html,
            "output_spec": output_spec_html,
            "sample_tests": sample_tests,
            "note": note_html
        }

    # ==================== 剥离 CF 自带的 section-title ====================
    def _strip_cf_section_titles(self, html_text):
        """移除 Codeforces HTML 中自带的 <div class="section-title">...</div>，
        避免与模板中自定义的标题重复显示。"""
        if not html_text:
            return html_text
        soup = BeautifulSoup(html_text, 'html.parser')
        for div in soup.find_all('div', class_='section-title'):
            div.decompose()
        return str(soup)

    # ==================== 数学公式保护 ====================
    def _protect_math(self, text: str) -> tuple:
        if not text:
            return "", []
        formulas = []

        def _replace(match):
            formulas.append(match.group(0))
            return f"MATHX{len(formulas) - 1}X"

        text = re.sub(r'\$\$(.+?)\$\$', _replace, text, flags=re.DOTALL)
        text = re.sub(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', _replace, text, flags=re.DOTALL)
        text = re.sub(r'\\$$(.+?)\\$$', _replace, text, flags=re.DOTALL)
        text = re.sub(r'\\$$(.+?)\\$$', _replace, text, flags=re.DOTALL)
        return text, formulas

    def _restore_math(self, text: str, formulas: list) -> str:
        if not text or not formulas:
            return text or ""
        for i, formula in enumerate(formulas):
            text = text.replace(f"MATHX{i}X", formula)
        return text

    # ==================== LLM 翻译 ====================
    async def _translate_to_chinese(self, description: str, input_spec: str,
                                     output_spec: str, note: str):
        try:
            provider = self.context.get_using_provider()
            if not provider:
                logger.warning("未配置 LLM 提供者，跳过翻译")
                return None
        except Exception as e:
            logger.warning(f"获取 LLM 提供者失败: {e}")
            return None

        desc_safe, desc_fx = self._protect_math(description)
        input_safe, input_fx = self._protect_math(input_spec)
        output_safe, output_fx = self._protect_math(output_spec)
        note_safe, note_fx = self._protect_math(note)

        combined = (
            f"<<<DESC_START>>>\n{desc_safe.strip()}\n<<<DESC_END>>>\n"
            f"<<<INPUT_START>>>\n{input_safe.strip()}\n<<<INPUT_END>>>\n"
            f"<<<OUTPUT_START>>>\n{output_safe.strip()}\n<<<OUTPUT_END>>>\n"
            f"<<<NOTE_START>>>\n{note_safe.strip()}\n<<<NOTE_END>>>"
        )

        system_prompt = (
            "你是 Codeforces 竞赛题目翻译助手，将英文题目 HTML 内容翻译为中文。\n"
            "严格要求：\n"
            "1. 保留所有 MATHX0, MATHX1 等占位符原样不变\n"
            "2. 保留所有 HTML 标签原样不变（<p>, <ul>, <li>, <div>, <span>, <br>, <b>, <i> 等）\n"
            "3. 只翻译 HTML 标签外的自然语言文本为中文\n"
            "4. 保留 <<<xxx_START>>> 和 <<<xxx_END>>> 分隔符原样不变\n"
            "5. 算法/竞赛术语使用常见中文译法（如 dynamic programming → 动态规划）\n"
            "6. 不要添加任何额外解释，只输出翻译后的带分隔符内容"
        )
        prompt = f"请翻译以下 Codeforces 题目内容：\n\n{combined}"

        try:
            try:
                response = await provider.text_chat(
                    prompt=prompt, contexts=[], system_prompt=system_prompt
                )
            except TypeError:
                full_prompt = f"[系统指令]\n{system_prompt}\n\n[用户内容]\n{prompt}"
                response = await provider.text_chat(prompt=full_prompt, contexts=[])

            if hasattr(response, 'completion_text'):
                result_text = response.completion_text
            elif isinstance(response, str):
                result_text = response
            else:
                result_text = str(response)

            translated = {}
            formulas_map = {
                "DESC": desc_fx, "INPUT": input_fx,
                "OUTPUT": output_fx, "NOTE": note_fx,
            }
            for key in ["DESC", "INPUT", "OUTPUT", "NOTE"]:
                pattern = rf'<<<{key}_START>>>(.*?)<<<{key}_END>>>'
                match = re.search(pattern, result_text, re.DOTALL)
                if match:
                    translated[key] = self._restore_math(
                        match.group(1).strip(), formulas_map[key]
                    )
                else:
                    translated[key] = ""

            logger.info("题目翻译完成")
            return translated

        except Exception as e:
            logger.error(f"LLM 翻译失败: {e}")
            return None

    # ==================== 渲染并发送 ====================
    async def _render_and_send(self, event: AstrMessageEvent, problem: dict):
        contest_id = problem.get("contestId")
        index = problem.get("index")
        problem_url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
        tags = ", ".join(problem.get("tags", []))
        rating = problem.get("rating", "未知")

        corner_image_url = "https://free.picui.cn/free/2026/05/10/6a005b791eeac.png"

        statement = await self.fetch_problem_statement(contest_id, index)
        if not statement:
            yield event.plain_result(
                f"获取详细题面失败，仅显示基础信息：\n"
                f"标题: {problem.get('name')}\n难度: {rating}\n链接: {problem_url}"
            )
            return

        def process_cf_html(text):
            if not text:
                return ""
            text = re.sub(r'\$\$\$(.*?)\$\$\$', r'\\(\1\\)', text, flags=re.DOTALL)
            return text

        description = process_cf_html(statement["description"])
        input_spec = process_cf_html(self._strip_cf_section_titles(statement["input_spec"]))
        output_spec = process_cf_html(self._strip_cf_section_titles(statement["output_spec"]))
        note = process_cf_html(self._strip_cf_section_titles(statement["note"]))

        samples_html = ""
        if statement["sample_tests"]:
            for i, sample in enumerate(statement["sample_tests"]):
                samples_html += f'''
                <div class="sample-columns">
                    <div class="sample-col sample-col-in">
                        <div class="sample-label label-in">输入 #{i+1}</div>
                        <pre class="pre-in">{sample["input"]}</pre>
                    </div>
                    <div class="sample-col sample-col-out">
                        <div class="sample-label label-out">输出 #{i+1}</div>
                        <pre class="pre-out">{sample["output"]}</pre>
                    </div>
                </div>'''

        tags_html = " ".join(
            [f'<span class="tag">{t.strip()}</span>' for t in tags.split(",") if t.strip()]
        )

        translated = await self._translate_to_chinese(
            description, input_spec, output_spec, note
        )
        has_translation = translated and any(
            v.strip() for v in translated.values()
        )

        # ============ 公共 CSS ============
        common_css = r'''
            html, body {
                margin: 0; padding: 0;
                background:
                    radial-gradient(ellipse at 5% 15%, rgba(195,175,225,0.50) 0%, transparent 45%),
                    radial-gradient(ellipse at 92% 8%,  rgba(160,195,235,0.40) 0%, transparent 40%),
                    radial-gradient(ellipse at 10% 85%, rgba(160,210,225,0.30) 0%, transparent 40%),
                    radial-gradient(ellipse at 88% 88%, rgba(235,200,185,0.35) 0%, transparent 40%),
                    #f0ecf5;
                overflow-x: hidden;
            }
            body {
                font-family: "PingFang SC","Segoe UI","Helvetica Neue",Arial,sans-serif;
                color: #2d2d3a; line-height: 1.6; padding: 32px;
            }

            /* ★ 卡片：加边框 */
            .card {
                background: #fff;
                border-radius: 22px;
                border: 1px solid #e0daf0;
                padding: 40px 44px;
                max-width: 1200px;
                margin: 0 auto;
                box-shadow: 0 4px 32px rgba(0,0,0,0.06);
                position: relative;
            }

            .header { margin-bottom: 16px; }
            .title  { font-size: 30px; font-weight: 800; color: #1a1a2e; margin: 0 0 4px 0; }
            .subtitle { color: #8b8ba0; font-size: 15px; margin: 0; }

            .info-bar { display: flex; gap: 14px; margin: 18px 0 24px 0; }
            .info-item {
                display: flex; align-items: center; gap: 10px;
                background: #f5f2fc; padding: 10px 20px; border-radius: 14px;
                border: 1px solid #ede8f5;
            }
            .info-icon { width: 22px; height: 22px; color: #9b8fbf; flex-shrink: 0; }
            .info-text  { display: flex; flex-direction: column; gap: 1px; }
            .info-label { color: #9b8fbf; font-size: 11px; }
            .info-value { font-size: 16px; font-weight: 700; color: #2d2d3a; }

            /* 双栏面板 */
            .dual-container {
                display: grid; grid-template-columns: 1fr 1fr; gap: 0;
                margin: 0 0 24px 0;
                border: 1px solid #ede8f5; border-radius: 16px; overflow: hidden;
            }
            .panel { padding: 28px; min-width: 0; }
            .panel-en { background: #f9f7ff; border-right: 1px solid #ede8f5; }
            .panel-cn { background: #fffcf8; }

            .panel-badge {
                display: inline-block; padding: 4px 18px;
                border-radius: 20px; font-size: 13px;
                font-weight: 600; margin-bottom: 14px;
            }
            .badge-en { background: #e0edfc; color: #4a90d9; }
            .badge-cn { background: #fde4e4; color: #d94a4a; }

            .section-title {
                font-size: 17px; font-weight: 700; color: #1a1a2e;
                margin: 20px 0 8px 0;
                padding-bottom: 6px; border-bottom: 1px solid rgba(0,0,0,0.06);
            }
            .panel .section-title:first-of-type { margin-top: 0; }

            .cf-content p                  { margin: 0 0 12px 0; font-size: 14px; }
            .cf-content ul, .cf-content ol { margin: 0 0 12px 0; padding-left: 22px; }
            .cf-content li                 { margin-bottom: 4px; font-size: 14px; }

            pre {
                border-radius: 10px; padding: 14px;
                font-family: "Consolas","SF Mono",monospace;
                font-size: 13px; overflow-x: auto; white-space: pre-wrap;
                margin: 6px 0 0 0;
            }

            /* ★ 样例区域 */
            .samples-section { margin: 4px 0 0 0; }
            .samples-title {
                font-size: 18px; font-weight: 700; color: #1a1a2e;
                margin-bottom: 14px;
            }

            /* ★ 输入输出左右分开，各自有独立背景和边框 */
            .sample-columns {
                display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
                margin-bottom: 14px;
            }
            .sample-col { min-width: 0; border-radius: 12px; padding: 14px; }

            .sample-col-in {
                background: #f5f0ff;
                border: 1px solid #e0d8f5;
            }
            .sample-col-out {
                background: #f0faf0;
                border: 1px solid #d0ecd0;
            }

            .sample-label {
                display: inline-block;
                padding: 3px 14px; border-radius: 8px;
                font-size: 13px; font-weight: 600;
                margin-bottom: 8px;
            }
            .label-in  { background: #e8dff8; color: #7c5cbf; }
            .label-out { background: #d8f0d8; color: #3a8a3a; }

            .pre-in  { background: #fff; border: 1px solid #e8e0f5; }
            .pre-out { background: #fff; border: 1px solid #d8eed8; }

            .note-content {
                background: #f5f2fc; padding: 14px;
                border-left: 4px solid #9b8fbf;
                border-radius: 0 10px 10px 0; font-size: 14px;
            }

            .tags {
                margin-top: 20px; padding-top: 16px;
                border-top: 1px solid #ede8f5;
            }
            .tag {
                display: inline-block;
                background: #f3f0fa; padding: 5px 14px;
                margin: 0 8px 8px 0; border-radius: 20px;
                font-size: 13px; color: #6b5b95;
                border: 1px solid #e8e3f5;
            }

            .translate-note {
                text-align: right; font-size: 11px;
                color: #b0a8c0; margin-top: 16px;
            }

            /* 右下角图片 */
            .corner-image {
                position: absolute;
                right: -10px;
                bottom: -10px;
                width: 180px;
                height: auto;
                opacity: 0.85;
                pointer-events: none;
                z-index: 1;
                border-radius: 12px;
            }
        '''

        # ============ 双栏模板 ============
        if has_translation:
            desc_cn = translated.get("DESC", "")
            input_cn = translated.get("INPUT", "")
            output_cn = translated.get("OUTPUT", "")
            note_cn = translated.get("NOTE", "")

            note_html_en = (
                f'<div class="section-title">Note</div>'
                f'<div class="note-content cf-content">{note}</div>' if note else ""
            )
            note_html_cn = (
                f'<div class="section-title">备注</div>'
                f'<div class="note-content cf-content">{note_cn}</div>' if note_cn else ""
            )

            tmpl = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <script>
                    window.MathJax = {{
                        tex: {{
                            inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                            displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                            processEscapes: true, processEnvironments: true
                        }},
                        svg: {{ fontCache: 'global' }},
                        options: {{ ignoreHtmlClass: 'no-mathjax' }}
                    }};
                </script>
                <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" id="MathJax-script" async></script>
                <style>{common_css}</style>
            </head>
            <body>
                <div class="card">
                    <div class="header">
                        <div class="title">{statement["title"]}</div>
                        <div class="subtitle">Codeforces {contest_id}{index} · 难度分：{rating}</div>
                    </div>

                    <div class="info-bar">
                        <div class="info-item">
                            <svg class="info-icon" viewBox="0 0 24 24" fill="none"
                                 stroke="currentColor" stroke-width="2"
                                 stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10"/>
                                <polyline points="12 6 12 12 16 14"/>
                            </svg>
                            <div class="info-text">
                                <span class="info-label">时间限制</span>
                                <span class="info-value">{statement["time_limit"]}</span>
                            </div>
                        </div>
                        <div class="info-item">
                            <svg class="info-icon" viewBox="0 0 24 24" fill="none"
                                 stroke="currentColor" stroke-width="2"
                                 stroke-linecap="round" stroke-linejoin="round">
                                <rect x="2" y="3" width="20" height="14" rx="2"/>
                                <line x1="8" y1="21" x2="16" y2="21"/>
                                <line x1="12" y1="17" x2="12" y2="21"/>
                            </svg>
                            <div class="info-text">
                                <span class="info-label">内存限制</span>
                                <span class="info-value">{statement["memory_limit"]}</span>
                            </div>
                        </div>
                    </div>

                    <div class="dual-container">
                        <div class="panel panel-en">
                            <span class="panel-badge badge-en">English</span>
                            <div class="section-title">Description</div>
                            <div class="cf-content">{description}</div>
                            <div class="section-title">Input</div>
                            <div class="cf-content">{input_spec}</div>
                            <div class="section-title">Output</div>
                            <div class="cf-content">{output_spec}</div>
                            {note_html_en}
                        </div>
                        <div class="panel panel-cn">
                            <span class="panel-badge badge-cn">中文翻译</span>
                            <div class="section-title">题目描述</div>
                            <div class="cf-content">{desc_cn}</div>
                            <div class="section-title">输入</div>
                            <div class="cf-content">{input_cn}</div>
                            <div class="section-title">输出</div>
                            <div class="cf-content">{output_cn}</div>
                            {note_html_cn}
                        </div>
                    </div>

                    <div class="samples-section">
                        <div class="samples-title">✦ 样例</div>
                        {samples_html}
                    </div>

                    <div class="tags">
                        <span class="tags-label">标签：</span><br>{tags_html}
                    </div>

                    <div class="translate-note">中文翻译由 LLM 自动生成，仅供参考</div>

                    <img class="corner-image" src="{corner_image_url}" alt="decoration"/>
                </div>
            </body>
            </html>
            '''

        # ============ 单栏回退模板 ============
        else:
            note_html_str = ""
            if note:
                note_html_str = (
                    f'<div class="section-title">Note</div>'
                    f'<div class="note-content cf-content">{note}</div>'
                )

            tmpl = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <script>
                    window.MathJax = {{
                        tex: {{
                            inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                            displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                            processEscapes: true, processEnvironments: true
                        }},
                        svg: {{ fontCache: 'global' }},
                        options: {{ ignoreHtmlClass: 'no-mathjax' }}
                    }};
                </script>
                <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" id="MathJax-script" async></script>
                <style>
                    {common_css}
                    .card {{ max-width: 900px; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="header">
                        <div class="title">{statement["title"]}</div>
                        <div class="subtitle">Codeforces {contest_id}{index} · 难度分：{rating}</div>
                    </div>

                    <div class="info-bar">
                        <div class="info-item">
                            <svg class="info-icon" viewBox="0 0 24 24" fill="none"
                                 stroke="currentColor" stroke-width="2"
                                 stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10"/>
                                <polyline points="12 6 12 12 16 14"/>
                            </svg>
                            <div class="info-text">
                                <span class="info-label">时间限制</span>
                                <span class="info-value">{statement["time_limit"]}</span>
                            </div>
                        </div>
                        <div class="info-item">
                            <svg class="info-icon" viewBox="0 0 24 24" fill="none"
                                 stroke="currentColor" stroke-width="2"
                                 stroke-linecap="round" stroke-linejoin="round">
                                <rect x="2" y="3" width="20" height="14" rx="2"/>
                                <line x1="8" y1="21" x2="16" y2="21"/>
                                <line x1="12" y1="17" x2="12" y2="21"/>
                            </svg>
                            <div class="info-text">
                                <span class="info-label">内存限制</span>
                                <span class="info-value">{statement["memory_limit"]}</span>
                            </div>
                        </div>
                    </div>

                    <div class="section-title">题目描述</div>
                    <div class="cf-content">{description}</div>
                    <div class="section-title">输入格式</div>
                    <div class="cf-content">{input_spec}</div>
                    <div class="section-title">输出格式</div>
                    <div class="cf-content">{output_spec}</div>
                    {note_html_str}

                    <div class="samples-section">
                        <div class="samples-title">✦ 样例</div>
                        {samples_html}
                    </div>

                    <div class="tags">
                        <span class="tags-label">标签：</span><br>{tags_html}
                    </div>

                    <img class="corner-image" src="{corner_image_url}" alt="decoration"/>
                </div>
            </body>
            </html>
            '''

        try:
            url = await self.html_render(tmpl, {})
            yield event.image_result(url)
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            yield event.plain_result(f"图片生成失败，请直接访问：{problem_url}")

    # ==================== 管理员重置 ====================
    @filter.command("cf重置")
    async def reset_daily(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        if self.admin_id is not None and user_id != self.admin_id:
            yield event.plain_result("❌ 权限不足，只有管理员可以重置。")
            return
        key = self._get_user_key(user_id)
        await self.put_kv_data(key, "0")
        yield event.plain_result("✅ 今日使用次数已重置为 0，可以继续使用「每日一题」了。")

    # ==================== 每日一题 ====================
    @filter.command("每日一题")
    async def daily_cf(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        has_quota, remaining = await self._check_quota(user_id)
        if not has_quota:
            yield event.plain_result(
                f"您今日的每日一题次数已用完（每日 {self.daily_limit} 次），请明天再来。"
            )
            return

        problems = await self.fetch_problemset()
        if problems is None:
            yield event.plain_result("获取题目列表失败，请稍后再试。")
            return

        message = event.message_str.strip()
        parts = message.split()
        a, b = None, None
        if len(parts) >= 3:
            try:
                a = int(parts[1])
                b = int(parts[2])
            except ValueError:
                pass

        if a is not None and b is not None and a <= b:
            filtered = [p for p in problems if "rating" in p and a <= p["rating"] <= b]
            range_desc = f"难度 {a}~{b}"
        else:
            filtered = [p for p in problems if "rating" in p]
            range_desc = "任意难度"

        if not filtered:
            yield event.plain_result(
                f"在 {range_desc} 区间内暂时没有合适的题目，请稍后再试或调整范围。"
            )
            return

        problem = random.choice(filtered)
        await self._increment_user_usage(user_id)

        name = problem.get("name", "未知标题")
        rating = problem.get("rating", "未知")
        tags = ", ".join(problem.get("tags", []))
        contest_id = problem.get("contestId")
        index = problem.get("index")
        problem_url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
        yield event.plain_result(
            f"今日一题已送达！\n标题: {name}\n难度分: {rating}\n标签: {tags}\n"
            f"链接：{problem_url}\n剩余次数: {remaining-1}/{self.daily_limit}"
        )

        async for result in self._render_and_send(event, problem):
            yield result

    async def terminate(self):
        pass