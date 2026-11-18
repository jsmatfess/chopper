"""Synthetic independent channel layouts; no actual-browser layout claim."""
import copy
import unittest
import uia


def layout(channel):
    node=lambda index,parent,cls,name,kind:dict(index=index,parent=parent,**{'class':cls},name=name,
        controlType='ControlType.'+kind,automationId='',enabled=True,offscreen=False)
    return dict(channel=channel,allowIndex=3,denyIndex=4,dialogIndex=1,destinationIndex=2,providerIndices=[],nodes=[
        node(0,-1,'Chrome_WidgetWin_1','Synthetic '+channel,'Window'),
        node(1,0,'RootView','Allow this site to edit files?','Window'),
        node(2,1,'Label','{origin} will be able to edit files in output','Text'),
        node(3,1,'MdTextButton','Allow','Button'),node(4,1,'MdTextButton',"Don't Allow",'Button')])


class Permission(unittest.TestCase):
    def observation(self,channel):
        reviewed=layout(channel);nodes=[]
        for template in reviewed['nodes']:
            r=dict(template);r['name']=r['name'].replace('{origin}','http://127.0.0.1:12345')
            r.update(processId=20,nativeHandle=100 if r['index']==0 else 0,depth=0 if r['index']==0 else 1 if r['index']==1 else 2)
            nodes.append(r)
        return dict(kind='owned-uia-tree',acceptance=False,actions=0,hwnd=100,nodes=nodes,truncated=False,foreignSkipped=0),reviewed

    def test_full_reviewed_channel_tree_and_exact_origin(self):
        for channel in ('chrome','msedge'):
            value,reviewed=self.observation(channel)
            digest=uia.permission_tree(value,100,{20:{}},dict(pid=20),'http://127.0.0.1:12345',reviewed)
            self.assertEqual(len(digest),64)
            for fault in ('origin','owner','name','enabled','offscreen','extra','hwnd'):
                changed=copy.deepcopy(value);origin='http://127.0.0.1:12345'
                if fault=='origin':origin='http://127.0.0.1:12346'
                elif fault=='owner':changed['nodes'][3]['processId']=21
                elif fault=='name':changed['nodes'][3]['name']="Don't Allow"
                elif fault=='enabled':changed['nodes'][3]['enabled']=False
                elif fault=='offscreen':changed['nodes'][3]['offscreen']=True
                elif fault=='extra':changed['nodes'].append(dict(changed['nodes'][-1],index=5))
                else:changed['nodes'][0]['nativeHandle']=99
                with self.subTest(channel=channel,fault=fault),self.assertRaises(AssertionError):
                    uia.permission_tree(changed,100,{20:{},21:{}},dict(pid=20),origin,reviewed)

    def test_missing_ambiguous_or_partial_review_does_not_reach_invoke(self):
        for fault in ('missing-node-key','duplicate-index','deny-as-allow','missing-origin','foreign-provider','offscreen-allow'):
            reviewed=layout('msedge')
            if fault=='missing-node-key':del reviewed['nodes'][3]['class']
            elif fault=='duplicate-index':reviewed['nodes'][3]['index']=4
            elif fault=='deny-as-allow':reviewed['allowIndex']=4
            elif fault=='missing-origin':reviewed['nodes'][2]['name']='output'
            elif fault=='foreign-provider':reviewed['providerIndices']=[2]
            else:reviewed['nodes'][3]['offscreen']=True
            with self.subTest(fault=fault),self.assertRaises(AssertionError):uia.layout_spec(reviewed)

    def test_two_reviewed_edge_root_captions_preserve_complete_tree(self):
        value,reviewed=self.observation('msedge')
        reviewed['rootNames']=[reviewed['nodes'][0]['name'],'Synthetic Personal']
        for caption in reviewed['rootNames']:
            value['nodes'][0]['name']=caption
            uia.permission_tree(value,100,{20:{}},dict(pid=20),'http://127.0.0.1:12345',reviewed)
        for index,node in enumerate(value['nodes']):
            for key in reviewed['nodes'][index]:
                changed=copy.deepcopy(value)
                old=changed['nodes'][index][key]
                changed['nodes'][index][key]=not old if type(old) is bool else old+1 if type(old) is int else old+' drift'
                with self.subTest(index=index,key=key),self.assertRaises(AssertionError):
                    uia.permission_tree(changed,100,{20:{}},dict(pid=20),'http://127.0.0.1:12345',reviewed)
        for fault in ('root-owner','provider','hwnd','origin'):
            changed=copy.deepcopy(value);origin='http://127.0.0.1:12345'
            if fault in ('root-owner','provider'):changed['nodes'][0 if fault=='root-owner' else 1]['processId']=21
            elif fault=='hwnd':changed['nodes'][0]['nativeHandle']=99
            else:origin='http://127.0.0.1:12346'
            with self.subTest(fault=fault),self.assertRaises(AssertionError):
                uia.permission_tree(changed,100,{20:{},21:{}},dict(pid=20),origin,reviewed)

    def test_root_caption_scope_is_optional_edge_only_and_bounded(self):
        for names in ([],['a','b','c'],['a','a'],'a',[1],['{origin}'],['x'*257],['not canonical']):
            reviewed=layout('msedge');reviewed['rootNames']=names
            with self.subTest(names=names),self.assertRaises(AssertionError):uia.layout_spec(reviewed)
        reviewed=layout('chrome');reviewed['rootNames']=[reviewed['nodes'][0]['name']]
        with self.assertRaises(AssertionError):uia.layout_spec(reviewed)
