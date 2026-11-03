# -*- coding: utf-8 -*-
"""扩展品牌图标来源。

官方目录里的部分第三方扩展被镜像到 Anthropic 仓库，不能用仓库所有者
代表扩展品牌。这里只维护确实需要纠正的品牌主页；其余条目仍使用目录里
明确提供的主页、作者或本地图标。
"""

BRAND_HOMEPAGES = {
    "asana": "https://asana.com",
    "context7": "https://upstash.com",
    "firebase": "https://firebase.google.com",
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "greptile": "https://greptile.com",
    "laravel-boost": "https://laravel.com",
    "linear": "https://linear.app",
    "playwright": "https://playwright.dev",
    "serena": "https://oraios.github.io/serena/",
    "terraform": "https://www.terraform.io",
}


def homepage(plugin_name):
    key = str(plugin_name or "").strip().lower().split("@", 1)[0]
    return BRAND_HOMEPAGES.get(key, "")
