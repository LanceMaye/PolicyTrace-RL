from copy import deepcopy
import pytest

from policytrace.data.manifests import digest
from policytrace.data.provenance import classify_pair, extract_entities
from policytrace.data.cost_filter import cost_pruned_view


def complete():
    # SYNTHETIC fully known case, not a claim about missing real SFT metadata.
    return {'entities':{'users':['synthetic_customer'], 'orders':['synthetic_order'],'emails':[]},
            'labels':['return'],'compatible_snapshots':['synthetic_initial'], 'reason_hash':digest('synthetic reason'),
            'mutation_actions':[{'name':'return_delivered_order_items','arguments':{'order_id':'synthetic_order'}}],
            **{k:digest(k) for k in ('identity_hash','objects_hash','goal_hash','constraints_hash','completion_hash','initial_state_hash')}}


def test_complete_same_instance_can_be_confirmed():
    a = complete()
    assert classify_pair(a,deepcopy(a))[0] == 'confirmed_same_instance'


@pytest.mark.parametrize('field', ['identity_hash','objects_hash','goal_hash','constraints_hash','completion_hash','initial_state_hash'])
def test_changed_customer_object_goal_constraint_completion_or_initial_state_is_not_confirmed(field):
    a,b = complete(),complete(); b[field]=digest('changed '+field)
    assert classify_pair(a,b)[0] != 'confirmed_same_instance'


@pytest.mark.parametrize('missing', [None, '', 'unknown'])
def test_missing_evidence_is_never_equality(missing):
    a,b = complete(),complete(); a['constraints_hash']=missing; b['constraints_hash']=missing
    assert classify_pair(a,b)[0] == 'probable_same_instance'


def test_same_business_different_customer_order_is_pattern_only():
    a,b = complete(),complete(); b['identity_hash']=digest('another customer'); b['objects_hash']=digest('another order')
    b['entities']={'users':['other'],'orders':['other'],'emails':[]}
    assert classify_pair(a,b)[0] == 'same_business_pattern_only'


def test_retrieval_never_treats_payment_ids_as_customers():
    e = extract_entities([], 'gift_card_123456 credit_card_7777 alice_smith_42')
    assert e['users'] == ['alice_smith_42']


@pytest.mark.parametrize('classification', ['probable_same_instance','same_business_pattern_only','distinct_or_unknown'])
def test_unconfirmed_cost_candidates_are_retained(classification):
    e = {'task_id':'r','source_dialog_id':'s','classification':classification,'confidence':'unconfirmed','missing_evidence':['constraints_hash']}
    kept,excluded = cost_pruned_view(['r'],['s'],[e])
    assert kept==['r'] and excluded==[]


def test_cost_filter_only_confirmed_train_to_train_and_rollback():
    e = {'task_id':'r','source_dialog_id':'s','classification':'confirmed_same_instance','confidence':'confirmed',
         'missing_evidence':[],'evidence_sha256':digest('synthetic proof'),'rule_id':'synthetic-complete'}
    assert cost_pruned_view(['r','other'],['s'],[e])[0] == ['other']
    assert cost_pruned_view(['r'],['not_s'],[e]) == (['r'],[])
    assert cost_pruned_view(['not_r'],['s'],[e]) == (['not_r'],[])
    assert set(cost_pruned_view(['r','other'],['s'],[e])[0]) <= {'r','other'}
