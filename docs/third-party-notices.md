# 第三方依赖与数据来源

本项目调用第三方开源组件。各组件随包提供的 LICENSE/NOTICE、具体版本的发行元数据及原仓库许可文件是其使用依据；本清单不替代那些文件，也不替项目自有源码指定发布许可证。

运行 `scripts/dependency-inventory.py` 可从当前 Python 环境元数据和前端 package-lock 生成 [版本与许可元数据清单](dependency-inventory.json)。清单包含传递依赖；未声明的字段会保留为未声明，不推断为可任意使用。Maven 依赖由 [pom.xml](../backend/pom.xml) 锁定直接版本，工具链下载与哈希记录在 [toolchain-lock.json](../backend/toolchain-lock.json)。

主要组件的官方来源：

| 组件 | 来源 / 许可文件 |
| --- | --- |
| Eclipse Temurin / OpenJDK | [Adoptium](https://adoptium.net/)；本地 JDK 的 legal 目录 |
| Apache Maven | [Maven 源码 LICENSE](https://github.com/apache/maven/blob/master/LICENSE) |
| Spring Boot | [Spring Boot LICENSE](https://github.com/spring-projects/spring-boot/blob/main/LICENSE.txt) |
| Xerial SQLite JDBC | [SQLite JDBC](https://github.com/xerial/sqlite-jdbc) |
| React | [React LICENSE](https://github.com/facebook/react/blob/main/LICENSE) |
| Apache ECharts | [ECharts LICENSE](https://github.com/apache/echarts/blob/master/LICENSE) |
| Vite | [Vite LICENSE](https://github.com/vitejs/vite/blob/main/LICENSE) |
| Qlib | [Qlib LICENSE](https://github.com/microsoft/qlib/blob/main/LICENSE) |
| NumPy / pandas / SciPy | 各安装包的 dist-info/licenses 及项目官网 |
| scikit-learn | [scikit-learn COPYING](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) |
| LightGBM | [LightGBM LICENSE](https://github.com/microsoft/LightGBM/blob/master/LICENSE) |
| Alphalens reloaded | [Alphalens reloaded](https://github.com/stefan-jansen/alphalens-reloaded) |
| PyArrow | [Apache Arrow](https://arrow.apache.org/) |

## 行情来源单独处理

BaoStock 与 AKShare 是免费数据访问工具。工具开源不等于它获取的第三方数据有开放再分发许可。项目用于符合来源条款的个人研究；下载的行情保留在本机 `workspace`，不随源码提交或公开分发。

- BaoStock：参考 [发行页](https://pypi.org/project/baostock/) 和 [项目说明](http://www.baostock.com/)。实际已验证原始日线、后复权日线、交易日历与沪深300开盘指数。
- AKShare：参考 [股票接口文档](https://akshare.akfamily.xyz/data/stock/stock.html) 及 [官方项目](https://github.com/akfamily/akshare)。适配器已实现；本次完整真实数据闭环使用 BaoStock，未将备用来源写成已完成同等实测。

每份快照记录来源、客户端版本、取得时间、价格调整、量额单位、交易日历、缺失证券、警告与哈希。再次取得供应商修订后的数据应生成新快照。

项目借鉴 Qlib 表达式和 Alphalens 的评价结构。报告指标的准确口径以本项目 quantitative-contract-v1 为准，未宣称复制 WorldQuant 的私有评价或 Fitness 算法。
