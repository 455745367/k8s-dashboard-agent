# encoding:utf-8

import json
import time
import logging
import httplib
import traceback
import requests

from django.conf import settings
from django.utils import timezone
from django.shortcuts import render
from django.http import *
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.views.decorators.csrf import csrf_exempt

RETU_INFO_SUCCESS = 200
RETU_INFO_ERROR = 201

from kd_agent.logconfig import LOGGING
logging.config.dictConfig( LOGGING )




# 一个装饰器，将原函数返回的json封装成response对象
def return_http_json(func):
    def wrapper( *arg1,**arg2 ):
        try:
            retu_obj = func( *arg1,**arg2 )
            logging.info( 'execute func %s success' % (func) )
        except Exception as reason:
            retu_obj = generate_failure( str(reason) )
            logging.error( 'execute func %s failure : %s' % (func,str(reason)) )
            traceback.print_exc()

        obj = HttpResponse( json.dumps(retu_obj) )
        obj['Access-Control-Allow-Origin'] = '*'
        obj['Content-Type'] = 'application/json'
        return obj
    return wrapper

def generate_retu_info( code,msg,**ext_info ):
    retu_data = { 'code':code,'msg':msg }
    for k in ext_info:
        retu_data[k] = ext_info[k]
    return retu_data

def generate_success(**ext_info):
    return generate_retu_info( RETU_INFO_SUCCESS,'',**ext_info )

def generate_failure( msg,**ext_info ):
    return generate_retu_info( RETU_INFO_ERROR,msg,**ext_info )

# 去掉时间字符串 2016-07-15T14:38:02Z 中的T、Z
def trans_time_str(time_str):
    return time_str[0:10] + ' ' + time_str[11:19]

# 根据原生的API获取k8s的数据
def get_k8s_data(url,params = {},timeout = 10 ):
    resp = None
    try:
        con = httplib.HTTPConnection(settings.K8S_IP, settings.K8S_PORT, timeout=timeout)
        con.request('GET', url, json.dumps(params, ensure_ascii=False))
        resp = con.getresponse()
        if not resp:
            s = 'get k8s data resp is not valid : %s' % resp
            logging.error( s )
            return generate_failure( s )

        if resp.status == 200:
            s = resp.read()
            logging.debug( 'get k8s data response : %s' % s )
            return generate_success( data = json.loads(s) )
        else:
            s = 'get k8s data status is not 200 : %s' % resp.status
            logging.error( s )
            return generate_failure( s )
    except Exception, e:
        s = "get k8s data occured exception : %s" % str(e)
        logging.error(s)
        return generate_failure( s )
    
def restore_k8s_path(p):
    return p.replace('/k8s','')


@csrf_exempt
@return_http_json
def get_pod_list(request,namespace):
    logging.info( 'call get_pod_list request.path : %s , namespace : %s' % (request.path,namespace) )
    pod_detail_info = get_k8s_data( restore_k8s_path(request.path) )
    if pod_detail_info['code'] == RETU_INFO_ERROR:
        logging.error( 'call get_pod_list query k8s data error : %s' % pod_detail_info['msg'] )
        return generate_failure( pod_detail_info['msg'] )

    retu_data = []
    for item in pod_detail_info['data']['items']:
        record = {}
        retu_data.append(record)
        record['Name'] = item['metadata']['name']
        record['CreationTime'] = trans_time_str(item['metadata']['creationTimestamp'])
        record['Node'] = item['spec']['nodeName']
        record['DetailInfo'] = trans_obj_to_easy_dis(item)

        containerStatuses = item['status']['containerStatuses']
        total = len(containerStatuses)
        running = 0
        for cItem in containerStatuses:
            if cItem['state'].get( 'running' ) != None:
                running += 1
        record['Ready'] = '%s / %s' % ( running,total )

        if total == running:
            record['Status'] = 'Running'
        else:
            #TODO:此处需要测试
            statusArr = []
            for cItem in containerStatuses:
                statusArr.append( cItem['state'][ cItem['state'].keys()[0] ]['reason'] )   
            record['Status'] = '{ %s }' % str(',').join( set(statusArr) )

        restartCountArr = []
        for cItem in containerStatuses:
            restartCountArr.append( cItem['restartCount'] )
        record['Restarts'] = sum(restartCountArr)
    
    logging.debug( 'call get_pod_list query k8s data : %s' % retu_data )
    logging.info( 'call get_pod_list query k8s data successful' )
    return generate_success( data = retu_data )


@csrf_exempt
@return_http_json
def get_service_list(request,namespace):
    logging.info( 'call get_service_list request.path : %s , namespace : %s' % (request.path,namespace) )
    service_detail_info = get_k8s_data( restore_k8s_path(request.path) )
    if service_detail_info['code'] == RETU_INFO_ERROR:
        logging.error( 'call get_service_list query k8s data error : %s' % service_detail_info['msg'] )
        return generate_failure( service_detail_info['msg'] )

    retu_data = []
    for item in service_detail_info['data']['items']:
        record = {}
        retu_data.append(record) 

        record['Name'] = item['metadata']['name']
        record['ClusterIP'] = item['spec']['clusterIP']
        record['ExternalIP'] = '<None-IP>'      #TODO:mini的测试暂时没有这个东西，这里暂时填充 <none-IP>
        record['CreationTime'] = trans_time_str( item['metadata']['creationTimestamp'] )
        record['DetailInfo'] = trans_obj_to_easy_dis(item)

        ports_info_arr = []
        for cItem in item['spec']['ports']:
            ports_info_arr.append( '%s/%s' % ( cItem['port'],cItem['protocol'] ) )
        record['Ports'] = str(',').join(ports_info_arr)

        if not item['spec'].get('selector'):
            record['Selector'] = '<None>'
        else:
            selector_info_arr = []
            for k,v in item['spec']['selector'].iteritems():
                selector_info_arr.append( '%s=%s' % (k,v) )
            record['Selector'] = str(',').join( selector_info_arr )

    logging.debug( 'call get_service_list query k8s data : %s' % retu_data )
    logging.info( 'call get_service_list query k8s data successful' )
    return generate_success( data = retu_data )


@csrf_exempt
@return_http_json
def get_rc_list(request,namespace):
    logging.info( 'call get_rc_list request.path : %s , namespace : %s' % (request.path,namespace) )
    rc_detail_info = get_k8s_data( restore_k8s_path(request.path) )
    if rc_detail_info['code'] == RETU_INFO_ERROR:
        logging.error( 'call get_rc_list query k8s data error : %s' % rc_detail_info['msg'] )
        return generate_failure( rc_detail_info['msg'] )

    retu_data = []
    for item in rc_detail_info['data']['items']:
        record = {}
        retu_data.append(record) 

        record['Name'] = item['metadata']['name']
        record['Desired'] = item['spec']['replicas']
        record['Current'] = item['status']['replicas']      #TODO:Current暂时这样取值
        record['CreationTime'] = trans_time_str( item['metadata']['creationTimestamp'] )
        record['DetailInfo'] = trans_obj_to_easy_dis(item)

        container_arr = []
        image_arr = []
        for cItem in item['spec']['template']['spec']['containers']:
            container_arr.append( cItem['name'] )
            image_arr.append( cItem['image'] )
        record['Containers'] = str(',').join( container_arr )
        record['Images'] = str(',').join( image_arr )
        
        if not item['spec'].get('selector'):
            record['Selector'] = '<None>'
        else:
            selector_info_arr = []
            for k,v in item['spec']['selector'].iteritems():
                selector_info_arr.append( '%s=%s' % (k,v) )
            record['Selector'] = str(',').join( selector_info_arr )
    
    logging.debug( 'call get_rc_list query k8s data : %s' % retu_data )
    logging.info( 'call get_rc_list query k8s data successful' )
    return generate_success( data = retu_data )

def trans_obj_to_easy_dis(obj_info):
    return json.dumps(obj_info, indent=1).split('\n')

'''
由于Pod、Service、RC的详情信息的展示方式暂时不确定，因此暂时使用最简单的json展示格式来展示
def __trans_obj_to_easy_dis(obj_info,head_str = 'obj'):
    
    将一个对象的所有属性转换成一种方便显示的方式，只支持dict、list这两种复合类型
    exam = { 'a':123,'b':[1,2,3] }
    将会被转换成：
    [
        'a = 123',
        'b[0] = 1',
        'b[1] = 2',
        'b[3] = 3'
    ]
    
    def trans_func( obj,head_str = 'obj' ):
        if isinstance( obj,dict ):
            temp = []
            for k in obj:
                temp += trans_func( obj[k],"%s['%s']" % ( head_str,str(k) ) )
            return temp
        elif isinstance( obj,list ):
            temp = []
            for i in range( len(obj) ):
                temp += trans_func( obj[i],head_str+str( '[%s]' % i ) )
            return temp
        else:
            return [ '%s = %s' % ( head_str,str(obj) ) ]
    retu_list = trans_func( obj_info,head_str )
    return retu_list
'''

@csrf_exempt
@return_http_json
def get_mytask_list(request):    
    logging.info( 'call get_mytask_list' )
    retu_data = []
    for record in Schedule_Status.objects.using('logging_bdms').filter(status=3L):
        d = {}
        retu_data.append(d) 
    
        d['task'] = str(record.query_name)
        d['category'] = record.category
        d['ready_time'] = format_datetime_obj(record.ready_time)
        d['running_time'] = format_datetime_obj(record.running_time)
        d['leave_time'] = format_datetime_obj(record.leave_time)
        d['status'] = record.status
        d['result'] = record.result
    
    logging.debug( 'call get_mytask_list query bdms data : %s' % retu_data )
    logging.info( 'call get_mytask_list query bdms data successful' )
    return generate_success( data = retu_data )

def format_datetime_obj(datetime_obj):
    if datetime_obj:
        return datetime_obj.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return '<None>'

@csrf_exempt
@return_http_json
def get_mytask_graph(request):
    logging.info( 'call get_mytask_graph' )
    url1 = 'http://' + settings.BDMS_IP + ':' + settings.BDMS_PORT + '/accounts/login/'  #模拟登陆BDMS
    url2 = 'http://' + settings.BDMS_IP + ':' + settings.BDMS_PORT + '/ide/schedule/directedgraphdata/?username=all&status=all&taskname=&env=0'  #任务运行网络图 rest api
    data={"username":settings.BDMS_USERNAME,"password": settings.BDMS_PASSWORD}
    headers = { "Accept":"*/*",
            "Accept-Encoding":"gzip, deflate, sdch",
            "Accept-Language":"zh-CN,zh;q=0.8",
            "Cache-Control":"no-cache",
            "Connection":"keep-alive",
            "Host":"172.24.2.114:10010",
            "Pragma":"no-cache",
            "Referer":"http://172.24.2.114:10010/ide/schedule/directedgraph/",
            "User-Agent":"Mozilla/5.0 (Windows NT 6.3; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.103 Safari/537.36",
            "X-Requested-With":"XMLHttpRequest"
            }
    try:
        req = requests.Session()
        r1 = req.post(url1, data=data, headers=headers)
        r2 = req.get(url2)
        if r1.status_code and r2.status_code == 200:
            logging.debug( 'get my task graph data success ')
            dic = eval(r2.text)
            all_task = []
            data = {}
            nodes = []
            for i in dic['task_info']:
                for j in dic['task_process']:
                    if i['exec_txt'] == dic['task_process'][j]['exec_txt'] and dic['task_process'][j]['result'] == 1:
                        nodes.append({"id": i["id"], "label": i["exec_txt"], "color": "#C2FABC"})
                    if i['exec_txt'] == dic['task_process'][j]['exec_txt'] and dic['task_process'][j]['result'] == 2:
                        nodes.append({"id": i["id"], "label": i["exec_txt"], "color": "#FF0000"})
            data["nodes"] = nodes
            data["edges"] = [{}]
            return generate_success( data=data )
        else:
            logging.error('get my tsk graph data error ')
            return generate_failure( 'get my tsk graph data error ' )
    except Exception, e:
        s = "get mytask graph data occured exception : %s" % str(e)
        logging.error(s)
        return generate_failure(s)




def generate_temp_data(id):
    d = {}
    d['id'] = id
    d['task'] = 'temp'
    d['category'] = 'temp'
    d['ready_time'] = 'temp'
    d['running_time'] = 'temp'
    d['leave_time'] = 'temp'
    d['status'] = 'temp'
    d['result'] = 'temp'
    return d

@csrf_exempt
@return_http_json
def mytask_get_old_records(request):
    oldestrecordid = int(request.GET.get('oldestrecordid'))
    retu_data = []
    for i in range(10):
        retu_data.append( generate_temp_data(oldestrecordid - 1 - i) )
    return generate_success( data = retu_data )

@csrf_exempt
@return_http_json
def mytask_check_has_new_records(request):
    return generate_success( hasnew = 1 )

@csrf_exempt
@return_http_json
def mytask_get_new_records(request):
    newestrecordid = int(request.GET.get('newestrecordid'))
    retu_data = []
    for i in range(3):
        retu_data.append( generate_temp_data(newestrecordid + 3 - i) )
    return generate_success( data = retu_data )







