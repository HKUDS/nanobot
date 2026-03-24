---
name: ipinfo
description: 查询本机公网IP、地理位置、运营商等信息，基于免费API，无需API key，无需安装依赖。
homepage: https://ipinfo.io/
metadata: {"nanobot":{"emoji":"🌐","requires":{"bins":["curl"]}}}
---

# IP/地理位置查询

无需API key，直接调用免费API，支持本机公网IP、地理位置、运营商、ASN等信息查询。

## 1. 查询本机公网IP及地理信息（推荐）

```bash
curl -s ipinfo.io
```

返回JSON，包含：
- ip：公网IP
- city/country/region：地理位置
- org：运营商/ASN
- loc：经纬度
- timezone：时区

## 2. 查询指定IP信息

```bash
curl -s ipinfo.io/8.8.8.8
```

## 3. 只查IP（纯文本）

```bash
curl -s ipinfo.io/ip
```

## 4. 其他可选API
- ip-api.com：
  ```bash
  curl -s ip-api.com/json
  ```
- ip.sb：
  ```bash
  curl -s ip.sb/jsonip
  ```

## 多语言支持

- ipinfo.io 支持根据请求头自动返回不同语言的地理位置描述。
- 可通过 curl 的 `-H` 参数设置 Accept-Language，例如：

```bash
curl -s ipinfo.io -H "Accept-Language: zh-CN"
```

- 如果输入为中文，建议加上上述参数，返回中文地理信息。
- 如果输入为英文，建议直接调用 ip-api.com 或 ip.sb 这类英文返回为主的免费API，例如：

```bash
curl -s ip-api.com/json
curl -s ip.sb/jsonip
```

- 也可以省略 Accept-Language，默认返回英文。

## Tips
- 支持IPv4/IPv6
- 适用于服务器、云主机、容器、桌面等所有环境
- 结果为JSON，便于二次处理

---

如需更详细ASN/运营商/批量查询，可参考 ipinfo.io 官网文档。
