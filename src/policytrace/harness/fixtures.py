"""Synthetic actions chosen from a Dev snapshot, never from scoring reference actions."""
import json

from .runner import DevTaskPool


def call(name, arguments):
    return '<tool_call>\n'+json.dumps({'name':name,'arguments':arguments},ensure_ascii=False)+'\n</tool_call>'


def fixture_scripts(task_id='retail_152'):
    _, snapshot = DevTaskPool().load(task_id)
    product_ids = sorted(snapshot.db.products)[:2]
    order = next(o for _,o in sorted(snapshot.db.orders.items()) if o.status=='pending')
    address = order.address.model_dump()
    address['zip'] = '00000'
    read = [call('get_product_details',{'product_id':p}) for p in product_ids]
    write = call('modify_pending_order_address',{'order_id':order.order_id,**address})
    read_order = call('get_order_details',{'order_id':order.order_id})
    bad_cancel = call('cancel_pending_order',{'order_id':order.order_id,'reason':'synthetic invalid reason'})
    return {
        'readonly': ([read[0],'Here are the requested product details.'],
            [f'Please look up product {product_ids[0]}.','###STOP###']),
        'write': ([read_order,'Please confirm this address change.',write,read_order,'The address change is recorded.'],
            [f'Please change the postal code for order {order.order_id} to 00000.','Yes, please confirm the change.','###STOP###']),
        'multi_read': ([read[0]+'\n'+read[1],'Both lookups are complete.'],
            ['Synthetic protocol test: look up the two supplied products.','###STOP###']),
        'partial_write_error': ([write+'\n'+bad_cancel+'\n'+read_order,'The batch returned an error.'],
            ['Synthetic batch side-effect diagnostic; this is not a policy compliance claim.','###STOP###']),
        'mixed': (['Synthetic mixed content '+read[0],'The lookup is complete.'],
            ['Synthetic mixed-message diagnostic.','###STOP###'])}
