// Surge Script for Sorting and Renaming Nodes

// 节点分类优先级
const priorityOrder = ["AC", "BC", "Max", "Plus", "Ultra", "SC", "Pro", "Std", "Lite"];

// 分类并排序节点的函数
function sortAndRenameNodes(nodes) {
  const categorizedNodes = priorityOrder.reduce((obj, category) => {
    obj[category] = [];
    return obj;
  }, { Others: [] });

  // 分类节点
  nodes.forEach(node => {
    const category = priorityOrder.find(key => node.toLowerCase().includes(key.toLowerCase())) || "Others";
    categorizedNodes[category].push(node);
  });

  const sortedNodes = [];

  // 按优先级排序并重新编号
  priorityOrder.forEach(category => {
    if (categorizedNodes[category]) {
      categorizedNodes[category].forEach((node, index) => {
        const newIndex = String(index + 1).padStart(2, "0"); // 编号两位
        const renamedNode = node.replace(/(AC|Max|Plus|Ultra|Pro|Std|Lite) \d+/, `${category} ${newIndex}`); // 替换编号
        sortedNodes.push(renamedNode);
      });
    }
  });

  // 添加未分类的节点
  if (categorizedNodes["Others"].length > 0) {
    sortedNodes.push(...categorizedNodes["Others"]);
  }

  return sortedNodes;
}

// 从订阅响应中解析节点
function parseNodes(responseBody) {
  const lines = responseBody.split("\n"); // 按行分割
  const nodes = lines
    .filter(line => line.includes("= ss")) // 筛选包含 `= ss` 的行
    .map(line => line.split("=")[0].trim()); // 提取 `=` 前面的节点名称

  return nodes;
}

// 主逻辑
(async () => {
  const url = $request.url;

  try {
    console.log("请求的订阅链接：", url);

    // 检查订阅响应内容
    const responseBody = $response.body;
    if (!responseBody) {
      console.log("订阅内容为空！");
      $done({});
      return;
    }

    console.log("订阅原始内容：", responseBody); // 输出订阅内容

    // 提取节点名称
    const nodes = parseNodes(responseBody);
    console.log("解析到的节点名称：", nodes);

    if (nodes.length === 0) {
      console.log("未提取到任何节点！");
      $done({});
      return;
    }

    // 排序和重命名节点
    const sortedNodes = sortAndRenameNodes(nodes);
    console.log("排序后的节点列表：", sortedNodes);

    // 替换原始内容的节点部分
    const updatedBody = sortedNodes.map(node => `${node} = ss`).join("\n");

    console.log("处理后的订阅内容：", updatedBody);

    $done({ response: { body: updatedBody } });
  } catch (error) {
    console.log("处理订阅时出错：", error);
    $done({});
  }
})();
