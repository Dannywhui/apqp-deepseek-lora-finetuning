## 工程
    APQP系统装载AI评分功能
## 阶段
    1.0
## 阶段目标
    APQP后端与AI服务能够正常交互，AI服务能最终完成短时间内100次评分请求
## 交互流程
    1.APQP后端请求AI服务，携带参数：文档、评分问题、回调url
    2.AI服务接到1)的请求，生成唯一的编号id，返回给请求
    3.AI服务自行安排对文档和评分问题的思考
    4.AI服务完成一次思考后，请求1)中APQP提供的回调url，携带参数：编号id、回答
## AI服务提供的接口定义
### 接口-接收文档与评分问题 
**描述**: 对文档关于评分问题给出回应

- **请求URL**: `http://192.168.0.100:8000/api/v1/question_with_file` 请根据实际更改
- **请求方式**: `POST`
- **认证方式**: 暂无要求
- **权限要求**: 暂无要求

#### 请求头 (Headers)
| 参数名 | 是否必填 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| Content-Type | 是 | string | 固定值：`multipart/form-data` |

#### 请求参数 (Request Body)
*数据格式：`multipart/form-data`（混合表单）*

| 参数名 | 是否必填 | 类型 | 说明 | 示例值/限制 |
| :--- | :--- | :--- | :--- | :--- |
| file | 是 | **file** | 需评分的文档 | 支持文本文档、word、excel等常用文档，单文件大小<=5MB |
| question | 是 | string | 评分问题 | `针对语言逻辑性、数据使用进行评分`，限制长度1000 |
| callback_url | 否 | string | 如填写了，则将回答post至该url；未填写，则在本次请求中回复回答 | `http://192.168.0.233/controller/aianswer` |

#### 请求示例（Postman / cURL 格式）
**cURL 命令:**
```bash
curl -X POST http://192.168.0.100:8000/api/v1/question_with_file \
  -F "file=@/Users/me/某日工作报告.xlsx" \
  -F "question=针对语言逻辑性、数据使用进行评分" \
  -F "callback_url=http://192.168.0.233/controller/aianswer"
```

#### 返回示例
```json
**当callback_url有填写时: **
{
  "code": 0,
  "message": "success",
  "data": { seq_id: "APQP260710121" }
}
```
**当callback_url未填写时: **
```json
{
  "code": 0,
  "message": "success",
  "data": { "answer": "行文逻辑正常，数据使用量大......" }
}
```
**当出现异常报错时: **
在message中写入可对外报告的错误原因
```json
{
  "code": -1,
  "message": "评分服务报错：任务超出队列长度......",
  "data": null
}
```

## APQP回调url的接口定义
### 接口-接收编号问题的回答 
**描述**: 接收AI服务回传的编号对应问题的回答

- **请求URL**: `http://192.168.0.233/controller/aianswer` 使用时用实际callback_url
- **请求方式**: `POST`
- **认证方式**: 暂无要求
- **权限要求**: 暂无要求

#### 请求头 (Headers)
| 参数名 | 是否必填 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| Content-Type | 是 | string | 固定值：`application/json` |

#### 请求参数 (Request Body)
*数据格式: JSON*
| 参数名 | 是否必填 | 类型 | 说明 | 示例值 |
| :--- | :--- | :--- | :--- | :--- |
| seq_id | 是 | string | 某次question_with_file请求回复的seq_id | `APQP260710121` |
| answer | 是 | string | 对某次question_with_file请求的问题，AI思考后的回答 | `行文逻辑正常，数据使用量大......` |

**Body 示例：**
```json
{
  "seq_id": "APQP260710121",
  "remark": "行文逻辑正常，数据使用量大......"
}
```

#### 返回示例
```json
{
  "code": 0,
  "message": "success"
}
```