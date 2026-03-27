import vocablens.api.dependencies as deps


def test_legacy_dependencies_compat_exports_core_symbols():
    assert callable(deps.get_current_user)
    assert callable(deps.get_admin_token)
    assert callable(deps.get_uow_factory)


def test_legacy_dependencies_compat_exports_interaction_symbols():
    assert callable(deps.get_conversation_service)
    assert callable(deps.get_frontend_service)
    assert callable(deps.get_vocabulary_service)


def test_legacy_dependencies_compat_exports_product_symbols():
    assert callable(deps.get_subscription_service)
    assert callable(deps.get_session_engine)
    assert callable(deps.get_experiment_service)
