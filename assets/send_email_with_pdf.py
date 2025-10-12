#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQ 邮箱 PDF 附件发送脚本
支持自动打包 PDF、智能处理大文件、失败自动重试
"""

import os
import sys
import smtplib
import shutil
import time
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime

# ============================================
# 配置区域
# ============================================
SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465
ATTACH_LIMIT_MB = 45  # QQ 邮箱附件大小限制（MB）
MAX_RETRIES = 1  # 发送失败重试次数
RETRY_DELAY = 3  # 重试间隔（秒）
ZIP_NAME = 'all_pdf.zip'  # 压缩包名称

# ============================================
# 从环境变量读取配置
# ============================================
JM_DOWNLOAD_DIR = os.getenv('JM_DOWNLOAD_DIR', '/home/runner/work/jmcomic/download/')
EMAIL_FROM = os.getenv('EMAIL_FROM', '')
EMAIL_TO = os.getenv('EMAIL_TO', '')
EMAIL_PASS = os.getenv('EMAIL_PASS', '')
EMAIL_TITLE = os.getenv('EMAIL_TITLE', '')
EMAIL_CONTENT = os.getenv('EMAIL_CONTENT', '')


def log(message, level='INFO'):
    """输出日志"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")


def get_file_size_mb(file_path):
    """获取文件大小（MB，保留一位小数）"""
    size_bytes = os.path.getsize(file_path)
    return round(size_bytes / (1024 * 1024), 1)


def scan_pdf_files(pdf_dir):
    """扫描 PDF 文件并返回文件信息列表"""
    pdf_path = Path(pdf_dir)
    if not pdf_path.exists():
        log(f"PDF 目录不存在: {pdf_dir}", 'WARNING')
        return []
    
    pdf_files = sorted(pdf_path.glob('*.pdf'))
    file_info = []
    
    for pdf in pdf_files:
        size_mb = get_file_size_mb(pdf)
        file_info.append({
            'path': str(pdf),
            'name': pdf.name,
            'size_mb': size_mb
        })
    
    return file_info


def create_pdf_zip(pdf_dir, output_path):
    """将 PDF 目录打包为 ZIP"""
    log(f"开始打包 PDF 文件...")
    
    pdf_path = Path(pdf_dir)
    if not pdf_path.exists() or not list(pdf_path.glob('*.pdf')):
        log("PDF 目录为空，跳过打包", 'WARNING')
        return False
    
    try:
        # 删除旧的 ZIP 文件
        if os.path.exists(output_path):
            os.remove(output_path)
        
        # 创建新的 ZIP
        zip_base = str(Path(output_path).with_suffix(''))
        shutil.make_archive(zip_base, 'zip', pdf_dir)
        
        zip_size = get_file_size_mb(output_path)
        log(f"✅ 打包完成: {ZIP_NAME} ({zip_size} MB)")
        return True
        
    except Exception as e:
        log(f"打包失败: {e}", 'ERROR')
        return False


def build_email_content(pdf_files, zip_size_mb, is_large_file):
    """构建邮件正文"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 构建标题
    if EMAIL_TITLE:
        title = EMAIL_TITLE
    else:
        pdf_count = len(pdf_files)
        title = f"禁漫PDF已生成（共 {pdf_count} 本 · {today}）"
    
    # 构建正文
    if EMAIL_CONTENT:
        content = EMAIL_CONTENT + "\n\n"
    else:
        content = "✅ 你的禁漫 PDF 文件已准备就绪！\n\n"
    
    # 添加文件列表
    if pdf_files:
        content += f"{'=' * 50}\n"
        content += f"📚 共 {len(pdf_files)} 本 PDF：\n"
        content += f"{'=' * 50}\n"
        for file_info in pdf_files:
            content += f"  • {file_info['name']} ({file_info['size_mb']} MB)\n"
        content += f"{'=' * 50}\n\n"
    
    # 根据文件大小添加不同的提示
    if is_large_file:
        content += f"⚠️ 附件超过 {ATTACH_LIMIT_MB} MB，已自动存为 Artifact\n"
        content += f"请前往当前任务界面的 \"Artifacts\" 下载 {ZIP_NAME}\n\n"
        content += f"📦 ZIP 大小: {zip_size_mb} MB\n"
    else:
        content += f"📦 附件已打包为 {ZIP_NAME} ({zip_size_mb} MB)\n"
    
    content += "\n—— GitHub Actions 自动服务"
    
    return title, content


def send_email(title, content, zip_path=None, retry_count=0):
    """发送邮件（支持重试）"""
    smtp_conn = None
    try:
        # 创建邮件对象
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = title
        
        # 添加正文
        msg.attach(MIMEText(content, 'plain', 'utf-8'))
        
        # 添加附件（如果存在且不超过限制）
        if zip_path and os.path.exists(zip_path):
            zip_size_mb = get_file_size_mb(zip_path)
            if zip_size_mb <= ATTACH_LIMIT_MB:
                log(f"添加附件: {ZIP_NAME} ({zip_size_mb} MB)")
                with open(zip_path, 'rb') as f:
                    attachment = MIMEApplication(f.read())
                    attachment.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=('utf-8', '', ZIP_NAME)
                    )
                    msg.attach(attachment)
        
        # 连接 SMTP 服务器并发送
        log("正在连接 SMTP 服务器...")
        smtp_conn = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60)
        smtp_conn.login(EMAIL_FROM, EMAIL_PASS)
        log("✅ SMTP 登录成功")
        
        # 发送邮件
        smtp_conn.send_message(msg)
        log("✅ 邮件发送成功")
        
        # 关闭连接（忽略关闭时的错误）
        try:
            smtp_conn.quit()
        except:
            pass
        
        return True
            
    except smtplib.SMTPAuthenticationError:
        log("❌ SMTP 认证失败，请检查邮箱授权码", 'ERROR')
        return False
        
    except Exception as e:
        log(f"❌ 邮件发送失败: {e}", 'ERROR')
        
        # 确保连接关闭
        if smtp_conn:
            try:
                smtp_conn.quit()
            except:
                pass
        
        # 自动重试
        if retry_count < MAX_RETRIES:
            retry_count += 1
            log(f"🔄 {RETRY_DELAY} 秒后进行第 {retry_count} 次重试...", 'WARNING')
            time.sleep(RETRY_DELAY)
            return send_email(title, content, zip_path, retry_count)
        else:
            log(f"❌ 已达到最大重试次数 ({MAX_RETRIES})，发送失败", 'ERROR')
            return False


def main():
    """主函数"""
    log("=" * 60)
    log("📧 开始邮件发送任务")
    log("=" * 60)
    
    # 检查邮件配置
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASS]):
        log("⚠️ 邮件配置不完整，跳过发送", 'WARNING')
        log("需要配置: EMAIL_FROM, EMAIL_TO, EMAIL_PASS")
        return 0  # 返回 0（成功）以免中断 workflow
    
    log(f"📤 发件人: {EMAIL_FROM}")
    log(f"📥 收件人: {EMAIL_TO}")
    
    # 扫描 PDF 文件
    pdf_dir = Path(JM_DOWNLOAD_DIR) / 'pdf'
    log(f"📁 扫描目录: {pdf_dir}")
    
    pdf_files = scan_pdf_files(pdf_dir)
    
    if not pdf_files:
        log("⚠️ 未找到 PDF 文件", 'WARNING')
        # 仍然发送通知邮件
        title = f"禁漫下载任务完成 · {datetime.now().strftime('%Y-%m-%d')}"
        content = "下载任务已完成，但未生成 PDF 文件。\n\n—— GitHub Actions 自动服务"
        send_email(title, content)
        return 0
    
    # 显示文件列表
    log(f"✅ 找到 {len(pdf_files)} 个 PDF 文件:")
    total_size = 0
    for file_info in pdf_files:
        log(f"  • {file_info['name']} ({file_info['size_mb']} MB)")
        total_size += file_info['size_mb']
    log(f"📊 总大小: {total_size:.1f} MB")
    
    # 打包 ZIP
    zip_path = Path(JM_DOWNLOAD_DIR) / ZIP_NAME
    if not create_pdf_zip(pdf_dir, zip_path):
        log("❌ 打包失败，取消发送", 'ERROR')
        return 0  # 返回 0 不中断 workflow
    
    # 检查 ZIP 大小
    zip_size_mb = get_file_size_mb(zip_path)
    is_large_file = zip_size_mb > ATTACH_LIMIT_MB
    
    if is_large_file:
        log(f"⚠️ ZIP 文件过大 ({zip_size_mb} MB > {ATTACH_LIMIT_MB} MB)", 'WARNING')
        log("将发送通知邮件（不带附件）")
    
    # 构建邮件内容
    title, content = build_email_content(pdf_files, zip_size_mb, is_large_file)
    
    # 发送邮件
    log("=" * 60)
    if is_large_file:
        success = send_email(title, content)  # 不附加文件
    else:
        success = send_email(title, content, zip_path)
    
    log("=" * 60)
    
    if success:
        log("✅ 邮件任务完成")
        return 0
    else:
        log("⚠️ 邮件发送失败，但不影响主流程", 'WARNING')
        return 0  # 返回 0 确保不中断 workflow


if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        log("\n❌ 任务被用户中断", 'ERROR')
        sys.exit(1)
    except Exception as e:
        log(f"❌ 发生未预期的错误: {e}", 'ERROR')
        import traceback
        log(traceback.format_exc(), 'ERROR')
        sys.exit(0)  # 返回 0 不中断 workflow
